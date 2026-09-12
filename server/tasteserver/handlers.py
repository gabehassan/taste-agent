"""Job handlers: everything the worker does for a message."""
import logging
import re
import time
import uuid

from . import brain, db, media, memory, ratelimit, storage
from .prompts import copy as C
from .fetch import Extracted, canonical, extract

log = logging.getLogger("taste.handlers")
URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
REACTION_EMOJI = {"love": "❤️", "like": "👍", "dislike": "👎", "laugh": "😂", "emphasize": "‼️", "question": "❓"}


# ---- outbound ---------------------------------------------------------------------

def out(user, text, reply_to=None):
    """Queue a text for the transport. Enforces the per-user outbound cap."""
    limit = int(db.setting("rate_outbound_per_hour"))
    if db.outbound_sends_last_hour(user["id"]) >= limit:
        log.warning("outbound cap hit for user %s", user["id"])
        return None
    return db.queue_outbound(user["id"], text)


def react(user, message, reaction):
    """Queue a tapback on their message if their transport can do it."""
    if reaction in (None, "", "none"):
        return None
    caps = _capabilities(user)
    if user.get("transport") == "blooio":
        caps = caps | {"react", "typing"}
    if "react" not in caps or not message.get("external_id"):
        return None
    return db.q("""INSERT INTO messages(user_id, direction, kind, text, status, meta) VALUES (%s, 'out', 'reaction', NULL, 'queued', %s)
                   RETURNING id""", (user["id"], db.J({"reaction": reaction, "emoji": REACTION_EMOJI.get(reaction, "❤️"),
                                                       "target_external_id": message["external_id"], "chat_id": message.get("chat_id")})), one=True)["id"]


def instant_ack(user, msg, reaction="like"):
    """Poke feel: tapback the moment a link or photo lands, before any fetching. Blooio only (needs a chat id)."""
    if user.get("transport") != "blooio" or not msg.get("chat_id") or not msg.get("external_id"):
        return
    try:
        from . import blooio
        blooio.mark_read(msg["chat_id"])
        if reaction:
            blooio.react(msg["chat_id"], msg["external_id"], reaction)
        blooio.typing(msg["chat_id"], True)
    except Exception:
        log.exception("instant ack failed")


def _capabilities(user):
    rows = db.q("SELECT capabilities FROM handles WHERE user_id = %s", (user["id"],))
    caps = set()
    for r in rows:
        caps |= set(r["capabilities"] or [])
    return caps


# ---- voice stats --------------------------------------------------------------------

def update_voice(user, text):
    if not text or len(text) < 3:
        return
    v = (db.user_state(user["id"]).get("voice") or {"n": 0, "avg_len": 0, "lowercase": 0, "emoji": 0, "exclaim": 0})
    n = v["n"]
    letters = [c for c in text if c.isalpha()]
    lower = (sum(c.islower() for c in letters) / len(letters)) if letters else 1.0
    emoji = 1.0 if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text) else 0.0
    exclaim = 1.0 if ("!" in text or "lol" in text.lower() or "omg" in text.lower()) else 0.0
    k = min(n, 30)  # rolling average over ~30 messages
    v = {"n": n + 1, "avg_len": (v["avg_len"] * k + len(text)) / (k + 1), "lowercase": (v["lowercase"] * k + lower) / (k + 1),
         "emoji": (v["emoji"] * k + emoji) / (k + 1), "exclaim": (v["exclaim"] * k + exclaim) / (k + 1)}
    db.set_user_state(user["id"], voice=v)


# ---- ingest --------------------------------------------------------------------------

def _bump_profile_counter(user_id):
    db.set_user_state(user_id, items_since_profile=(db.user_state(user_id).get("items_since_profile") or 0) + 1)


def _clean_snippets(snips):
    out = []
    for x in snips or []:
        x = (x or "").strip().strip('“”"\'‘’').strip()
        if x:
            out.append(x)
    return out


def ingest_url(user, url, note="", message_id=None, job_id=None):
    can = canonical(url)
    existing = db.find_by_url(user["id"], can) or db.find_by_url(user["id"], url)
    if existing and existing["status"] != "pending":
        return existing, C("already_saved", title=existing["title"]), "like"
    if not ratelimit.check(f"ingest:{user['id']}", int(db.setting("rate_ingest_per_day")), 86400):
        return None, C("ingest_limit"), "none"
    ex = extract(url)
    item_key = uuid.uuid4().hex[:12]
    transcript, images, media_files, seconds = "", [], [], 0.0
    if ex.media_url and not ex.meta.get("has_captions"):
        m = media.process(ex.media_url, user["id"], item_key, duration=ex.meta.get("duration"), job_id=job_id)
        transcript, images, media_files, seconds = m.get("transcript", ""), m.get("frames", []), m.get("media", []), m.get("seconds", 0)
        if m.get("error"):
            ex.meta["media_error"] = m["error"]
    elif ex.thumbnail and ex.kind in ("tweet", "tiktok", "instagram", "youtube"):
        try:
            from . import netguard
            r = netguard.get(ex.thumbnail, max_bytes=3 * 1024 * 1024, timeout=15)
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
            if ct.startswith("image/"):
                images.append((ct, r.content))
        except Exception:
            pass
    d = brain.digest(user, ex, note=note, images=images, transcript=transcript, job_id=job_id)
    fields = dict(url=ex.url, canonical_url=can, kind=d.kind, source=ex.source, title=d.title or ex.title, author=ex.author,
                  raw_text=ex.text, transcript=transcript or None, summary=d.summary, snippets=_clean_snippets(d.snippets), tags=d.tags,
                  why=d.why_saved, read_minutes=d.read_minutes, note=note or None, message_id=message_id, media=media_files,
                  meta={**ex.meta, "thumbnail": ex.thumbnail, "media_seconds": seconds}, status="unread")
    if existing:
        db.update_item(existing["id"], **fields)
        item = db.get_item(user["id"], existing["id"])
    else:
        iid = db.add_item(user["id"], **fields)
        item = db.get_item(user["id"], iid)
    _bump_profile_counter(user["id"])
    log.info("user %s saved item %s [%s] %s", user["id"], item["id"], d.kind, d.title)
    return item, d.ack, d.reaction


def ingest_image(user, key, content_type, note="", message_id=None, job_id=None):
    data = storage.get(key)
    ex = Extracted(kind="screenshot", url="", title=(note or "screenshot")[:80], text=note, source="screenshot")
    d = brain.digest(user, ex, note=note or "(screenshot, no caption)", images=[(content_type, data)], job_id=job_id)
    iid = db.add_item(user["id"], url=None, kind=d.kind, source="screenshot", title=d.title, raw_text=d.summary, summary=d.summary,
                      snippets=_clean_snippets(d.snippets), tags=d.tags, why=d.why_saved, read_minutes=d.read_minutes, note=note or None,
                      message_id=message_id, media=[{"key": key, "type": content_type}], meta={"thumbnail_key": key})
    _bump_profile_counter(user["id"])
    return db.get_item(user["id"], iid), d.ack, d.reaction


# ---- commands ------------------------------------------------------------------------

CMD = {
    "pause": ("pause", "stop", "shut up", "quiet", "mute"),
    "resume": ("resume", "start", "unpause", "unmute"),
    "profile": ("taste", "profile", "my taste", "what do i like", "whats my taste", "what's my taste"),
    "surface": ("surface", "hit me", "random", "another", "something", "gimme", "next"),
    "more": ("more",),
    "later": ("later", "not now", "another day"),
    "skip": ("skip", "not for me", "not interested"),
    "read": ("read", "done", "finished", "read it", "watched", "watched it"),
    "status": ("status", "stats"),
    "help": ("help", "?", "what can you do"),
    "login": ("login", "log in", "dashboard", "link", "website", "sign in"),
}

HELP = ("send me links (articles, tweets, reddit, tiktok, youtube, goodreads), screenshots, or just a book title or a "
        "thought. i read them, keep them, and text you bits back a few times a day.\n\nwords i understand: taste, hit me, "
        "more, read, status, pause, resume. anything else and we just talk.")


def command_for(text):
    t = re.sub(r"[^\w\s?']", "", text.lower()).strip()
    for name, words in CMD.items():
        if t in words:
            return name
    return None


def do_surface(user, force_kind=None):
    kind, item, text = next_surface_and_log(user, force_kind)
    if not text:
        return out(user, C("nothing_saved"))
    return out(user, text)


def next_surface_and_log(user, force_kind=None):
    from .scheduler import next_surface
    kind, item, text = next_surface(user, force_kind)
    if not text:
        return None, None, None
    if item:
        db.update_item(item["id"], surfaced_count=item["surfaced_count"] + 1, last_surfaced_at=db.q("SELECT now() AS t", one=True)["t"])
    db.log_surface(user["id"], item["id"] if item else None, kind, text)
    return kind, item, text


def do_more(user):
    from .scheduler import format_surface
    last = db.last_surface(user["id"])
    if not last or not last.get("item_id"):
        return do_surface(user)
    item = db.get_item(user["id"], last["item_id"])
    if not item or len(item["snippets"]) < 2:
        return out(user, C("more_exhausted", url=(item["url"] or "") if item else ""))
    db.update_item(item["id"], surfaced_count=item["surfaced_count"] + 1)
    text = format_surface(db.get_item(user["id"], item["id"]))
    db.log_surface(user["id"], item["id"], "snippet", text)
    return out(user, text)


def do_profile(user, job_id=None):
    p = db.latest_profile(user["id"])
    if not p:
        if db.count_items(user["id"]) == 0:
            return out(user, C("no_profile_yet"))
        brain.refresh_profile(user, job_id=job_id)
        p = db.latest_profile(user["id"])
    text = (p["one_liner"] + "\n\n" if p.get("one_liner") else "") + p["text"]
    return out(user, text[:3500])


def do_status(user):
    n, unread = db.count_items(user["id"]), db.count_items(user["id"], "unread")
    p = db.latest_profile(user["id"])
    from .scheduler import todays_plan
    pending = [s["at"][11:16] for s in todays_plan(user)["slots"] if not s["done"]]
    paused = (user.get("settings") or {}).get("paused")
    return out(user, f"{n} saved, {unread} unread. profile built from {p['item_count'] if p else 0} items. "
                     f"{'paused' if paused else 'active'}. today's drops left: {', '.join(pending) or 'none'}. "
                     f"spent ${db.spend(user['id'], 1):.2f} today.")


WELCOME = ("hey. i'm taste.\n\nsend me anything you want to read, watch, or remember: links, tiktoks, tweets, screenshots, "
           "a book someone mentioned. i'll read it properly, keep it, and text you the good bits back when you've half forgotten them.\n\n"
           "over time i learn what you actually like. say 'taste' whenever you want to see what i've figured out.")


def do_login_link(user, phone=None):
    from fastapi import HTTPException
    from . import login
    try:
        return login.issue(user, phone)
    except HTTPException:
        return out(user, "couldn't send another code yet. wait a bit, then text login again.")



# ---- inbound dispatcher -----------------------------------------------------------------

def handle_message(job):
    msg = db.q("SELECT * FROM messages WHERE id = %s", (job["payload"]["message_id"],), one=True)
    if not msg:
        return
    user = db.get_user(msg["user_id"])
    if not user or user["status"] != "active":
        return
    if msg["kind"] == "reaction":
        return handle_reaction(user, msg)
    text = (msg["text"] or "").strip()
    update_voice(user, text)
    urls = URL_RE.findall(text)
    images = [a for a in (msg["attachments"] or []) if str(a.get("content_type", "")).startswith("image/")]

    if urls or images:
        ok, why = db.spend_ok(user)
        if not ok:
            if not db.user_state(user["id"]).get("cap_notified") == time.strftime("%Y-%m-%d"):
                out(user, C("spend_cap", why=why))
                db.set_user_state(user["id"], cap_notified=time.strftime("%Y-%m-%d"))
            for u in urls[:3]:
                db.add_item(user["id"], url=u, canonical_url=canonical(u), kind="link", title=u, summary="(pending)", status="pending",
                            note=URL_RE.sub("", text).strip() or None, message_id=msg["id"])
            return
    if urls or images:
        instant_ack(user, msg, "like")
    elif text and not command_for(text):
        instant_ack(user, msg, "")  # read receipt + typing only
    if urls:
        note = URL_RE.sub("", text).strip()
        for u in urls[:3]:
            try:
                item, ack, reaction = ingest_url(user, u, note=note, message_id=msg["id"], job_id=job["id"])
                react(user, msg, reaction)
                out(user, ack)
            except Exception as e:
                log.exception("ingest failed for %s", u)
                if not db.find_by_url(user["id"], canonical(u)):
                    db.add_item(user["id"], url=u, canonical_url=canonical(u), kind="link", title=u, summary="(pending)", status="pending",
                                note=note or None, message_id=msg["id"])
                out(user, C("fetch_failed", error=type(e).__name__))
        return
    if images:
        for a in images[:2]:
            try:
                item, ack, reaction = ingest_image(user, a["key"], a["content_type"], note=text, message_id=msg["id"], job_id=job["id"])
                react(user, msg, reaction)
                out(user, ack)
            except Exception:
                log.exception("image ingest failed")
                out(user, C("image_failed"))
        return
    if not text:
        return
    cmd = command_for(text)
    if cmd == "pause":
        db.q("UPDATE users SET settings = settings || '{\"paused\": true}' WHERE id = %s", (user["id"],))
        return out(user, C("paused"))
    if cmd == "resume":
        db.q("UPDATE users SET settings = settings - 'paused' WHERE id = %s", (user["id"],))
        return out(user, C("resumed"))
    if cmd == "profile":
        return do_profile(user, job_id=job["id"])
    if cmd == "surface":
        return do_surface(user)
    if cmd == "more":
        return do_more(user)
    if cmd in {"later", "skip"}:
        last = db.last_surface(user["id"])
        if last and last.get("item_id"):
            memory.feedback(user["id"], last["item_id"], "later" if cmd == "later" else "not_for_me")
            return out(user, "another day, then." if cmd == "later" else "got it. i'll leave that one alone.")
        return out(user, C("nothing_to_mark"))
    if cmd == "read":
        last = db.last_surface(user["id"])
        if last and last.get("item_id"):
            memory.feedback(user["id"], last["item_id"], "finished")
            return react(user, msg, "like") or out(user, C("marked_read"))
        return out(user, C("nothing_to_mark"))
    if cmd == "status":
        return do_status(user)
    if cmd == "help":
        return out(user, HELP)
    if cmd == "login":
        handle = db.q("SELECT address FROM handles WHERE id = %s", (msg.get("handle_id"),), one=True)
        return do_login_link(user, phone=handle["address"] if handle else None)
    ok, why = db.spend_ok(user)
    if not ok:
        return
    if not ratelimit.check(f"chat:{user['id']}", int(db.setting("rate_chat_per_day")), 86400):
        return out(user, C("chat_limit"))
    reply = brain.chat(user, text, job_id=job["id"])
    if reply:
        out(user, reply)


def handle_reaction(user, msg):
    """They tapped back on something we sent. Record it as taste signal."""
    meta = msg["meta"] or {}
    reaction, target = meta.get("reaction"), meta.get("target_external_id")
    if not reaction or not target:
        return
    ours = db.q("SELECT * FROM messages WHERE user_id = %s AND direction = 'out' AND external_id = %s", (user["id"], target), one=True)
    if not ours:
        return
    surf = db.q("SELECT * FROM surfaces WHERE user_id = %s AND text = %s ORDER BY id DESC LIMIT 1", (user["id"], ours["text"]), one=True)
    item_id = surf["item_id"] if surf else None
    if not item_id:
        item = db.q("SELECT id FROM items WHERE user_id = %s AND message_id IS NOT NULL ORDER BY id DESC LIMIT 1", (user["id"],), one=True)
        item_id = item["id"] if item else None
    if item_id:
        it = db.get_item(user["id"], item_id)
        reactions = list(((it.get("meta") or {}).get("reactions") or []))
        reactions.append(reaction)
        db.update_item(item_id, meta={**(it.get("meta") or {}), "reactions": reactions[-10:]})
        if reaction == "dislike":
            db.update_item(item_id, status="archived")
        log.info("user %s reacted %s on item %s", user["id"], reaction, item_id)


# ---- periodic ------------------------------------------------------------------------------

def surface_tick():
    from .scheduler import due_slot, mark_slot_done
    for user in db.q("SELECT * FROM users WHERE status = 'active'"):
        try:
            with db.transaction():
                user = db.q("SELECT * FROM users WHERE id=%s FOR NO KEY UPDATE", (user["id"],), one=True)
                i = due_slot(user)
                if i is None:
                    continue
                mark_slot_done(user, i)
            do_proactive(user)
        except Exception:
            log.exception("surface tick failed for %s", user["id"])


def do_proactive(user):
    from .scheduler import proactive_candidates
    from .config import DASHBOARD_URL
    candidates = proactive_candidates(user)
    if not candidates or not db.spend_ok(user)[0]:
        return None
    choice = brain.proactive_choice(user, candidates)
    item = next((i for i in candidates if i["id"] == choice.item_id), None)
    if not choice.send or not item or not 0 <= choice.excerpt_index < min(4, len(item["snippets"])) or not choice.connection.strip():
        return None
    # The model picks an index; it never writes or rewrites the quotation.
    quote = item["snippets"][choice.excerpt_index][:1000].strip().strip('“”"')
    text = f"{choice.connection.strip()}\n\n“{quote}”\n— {item['title']}\n\n{DASHBOARD_URL.rstrip('/')}/items/{item['id']}"
    with db.transaction():
        fresh = db.q("SELECT * FROM items WHERE id=%s AND user_id=%s FOR UPDATE", (item["id"], user["id"]), one=True)
        if not fresh or not memory.eligible(fresh):
            return None
        mid = out(user, text)
        if mid is None:
            return None
        db.q("UPDATE messages SET meta=meta || %s WHERE id=%s", (db.J({"proactive": True, "item_id": item["id"], "reason": choice.reason}), mid))
        db.update_item(item["id"], surfaced_count=fresh["surfaced_count"] + 1, last_surfaced_at=db.q("SELECT now() AS t", one=True)["t"])
        db.log_surface(user["id"], item["id"], "proactive", text)
        return mid


def profile_tick():
    every = int(db.setting("profile_refresh_every"))
    max_age = int(db.setting("profile_max_age_hours"))
    for user in db.q("SELECT * FROM users WHERE status = 'active'"):
        n = db.user_state(user["id"]).get("items_since_profile") or 0
        if n == 0:
            continue
        p = db.latest_profile(user["id"])
        stale = (not p) or (db.q("SELECT now() AS t", one=True)["t"] - p["created_at"]).total_seconds() > max_age * 3600
        if n >= every or stale:
            if db.spend_ok(user)[0]:
                db.enqueue(user["id"], "refresh_profile")
                db.set_user_state(user["id"], items_since_profile=0)


def retry_pending():
    for it in db.q("SELECT * FROM items WHERE status = 'pending' AND url IS NOT NULL ORDER BY id LIMIT 20"):
        user = db.get_user(it["user_id"])
        if user and db.spend_ok(user)[0]:
            db.enqueue(user["id"], "ingest_url", {"url": it["url"], "note": it.get("note") or "", "item_id": it["id"]})
            db.update_item(it["id"], status="retrying")


def run_job(job):
    t = job["type"]
    if t == "handle_message":
        return handle_message(job)
    if t == "ingest_url":
        user = db.get_user(job["user_id"])
        item, ack, _ = ingest_url(user, job["payload"]["url"], note=job["payload"].get("note", ""), job_id=job["id"])
        if item and job["payload"].get("item_id") and item["id"] != job["payload"]["item_id"]:
            db.q("DELETE FROM items WHERE id = %s AND status IN ('pending', 'retrying')", (job["payload"]["item_id"],))
        if ack and job["payload"].get("notify", True):
            out(user, ack)
        return
    if t == "refresh_profile":
        return brain.refresh_profile(db.get_user(job["user_id"]), job_id=job["id"])
    if t == "surface":
        return do_surface(db.get_user(job["user_id"]), job["payload"].get("kind"))
    if t == "sync_connection":
        from .connections import sync
        return sync(job["payload"]["connection_id"])
    raise RuntimeError(f"unknown job type {t}")
