"""Main loop: watch the self-chat, ingest, reply, resurface."""
import logging
import re
import time
import traceback

from . import brain, db, imessage, scheduler
from .config import (LOG_PATH, MAX_SENDS_PER_HOUR, POLL_SECONDS, PROFILE_MAX_AGE_HOURS,
                     PROFILE_REFRESH_EVERY)
from .fetch import extract

log = logging.getLogger("taste")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


# ---- sending ---------------------------------------------------------------

def say(text):
    if db.sends_in_last_hour() >= MAX_SENDS_PER_HOUR:
        log.warning("send cap hit, dropping: %s", text[:80])
        return False
    db.log_sent(text.strip())
    imessage.send(text)
    log.info("sent: %s", text[:120].replace("\n", " / "))
    return True


# ---- ingestion -------------------------------------------------------------

def ingest_url(url, note="", msg_rowid=None, image=None):
    existing = db.find_by_url(url)
    if existing:
        return existing, f"already saved that one ({existing['title']}). want a snippet from it?"
    ex = extract(url)
    d = brain.digest(ex, note=note, image=image)
    iid = db.add_item(
        url=ex.url, kind=d.kind, source=ex.source, title=d.title or ex.title, author=ex.author,
        raw_text=ex.text, summary=d.summary, snippets=d.snippets, tags=d.tags, why=d.why_saved,
        read_minutes=d.read_minutes, note=note or None, msg_rowid=msg_rowid,
    )
    db.set_state("items_since_profile", (db.get_state("items_since_profile", 0) or 0) + 1)
    log.info("saved item %s [%s] %s", iid, d.kind, d.title)
    return db.get_item(iid), d.ack


def ingest_image(path, note="", msg_rowid=None):
    img = imessage.image_bytes(path)
    if not img:
        return None, None
    from .fetch import Extracted
    ex = Extracted(kind="screenshot", url="", title=note[:80] or "screenshot", text=note, source="screenshot")
    d = brain.digest(ex, note=note or "(screenshot, no caption)", image=img)
    iid = db.add_item(
        url=None, kind=d.kind, source="screenshot", title=d.title, raw_text=d.summary,
        summary=d.summary, snippets=d.snippets, tags=d.tags, why=d.why_saved,
        read_minutes=d.read_minutes, note=note or None, msg_rowid=msg_rowid,
    )
    db.set_state("items_since_profile", (db.get_state("items_since_profile", 0) or 0) + 1)
    log.info("saved screenshot item %s %s", iid, d.title)
    return db.get_item(iid), d.ack


def failure_ack(e):
    msg = str(e)
    if "credit balance" in msg or "billing" in msg.lower():
        return "saved the link, but my api key is out of credits so i can't read it yet. top up at console.anthropic.com and i'll catch up on my own."
    if "api_key" in msg.lower() or "authentication" in msg.lower():
        return "saved the link, but my api key isn't working. i'll retry once it's fixed."
    return f"saved the link but couldn't read it ({type(e).__name__}). i'll retry in a bit."


def retry_pending():
    """Re-digest links that failed earlier (no credits, site down, ...). Runs every 10 min."""
    last = db.get_state("last_retry", 0) or 0
    if time.time() - last < 600:
        return
    db.set_state("last_retry", time.time())
    pending = db.list_items(limit=20, status="pending")
    for it in pending:
        try:
            ex = extract(it["url"])
            d = brain.digest(ex, note=it.get("note") or "")
        except Exception as e:
            log.info("retry still failing for %s: %s", it["url"], str(e)[:120])
            return  # same cause will hit the rest; try again next round
        db.update_item(it["id"], url=ex.url, kind=d.kind, source=ex.source, title=d.title or ex.title,
                       author=ex.author, raw_text=ex.text, summary=d.summary, snippets=d.snippets,
                       tags=d.tags, why=d.why_saved, read_minutes=d.read_minutes, status="unread")
        db.set_state("items_since_profile", (db.get_state("items_since_profile", 0) or 0) + 1)
        log.info("retried and saved item %s [%s] %s", it["id"], d.kind, d.title)
        say(f"caught up on one: {d.title}. {d.ack}")


# ---- commands --------------------------------------------------------------

CMD = {
    "pause": ("pause", "stop", "shut up", "quiet"),
    "resume": ("resume", "start", "unpause"),
    "profile": ("taste", "profile", "my taste", "what do i like"),
    "surface": ("surface", "hit me", "random", "another", "something", "gimme"),
    "more": ("more",),
    "read": ("read", "done", "finished", "read it"),
    "status": ("status", "stats"),
    "help": ("help", "?"),
}


def command_for(text):
    t = re.sub(r"[^\w\s?]", "", text.lower()).strip()
    for name, words in CMD.items():
        if t in words:
            return name
    return None


def do_surface(force_kind=None):
    kind, item, text = scheduler.next_surface(force_kind)
    if not text:
        return say("nothing saved yet. send me a link.")
    if item:
        db.update_item(item["id"], surfaced_count=item["surfaced_count"] + 1, last_surfaced_at=time.time())
    db.log_surface(item["id"] if item else None, kind, text)
    return say(text)


def do_more():
    last = db.last_surface()
    if not last or not last.get("item_id"):
        return do_surface()
    item = db.get_item(last["item_id"])
    if not item or len(item["snippets"]) < 2:
        return say("that's all i pulled from that one. " + (item["url"] or ""))
    db.update_item(item["id"], surfaced_count=item["surfaced_count"] + 1, last_surfaced_at=time.time())
    text = scheduler.format_surface(db.get_item(item["id"]))
    db.log_surface(item["id"], "snippet", text)
    return say(text)


def do_profile():
    p = db.latest_profile()
    if not p:
        if db.count_items() == 0:
            return say("no profile yet. send me a few things first.")
        p = brain.refresh_profile()
        p = db.latest_profile()
    one = db.get_state("one_liner")
    text = (one + "\n\n" if one else "") + p["text"]
    return say(text[:3500])


def do_status():
    n = db.count_items()
    unread = len(db.list_items(limit=1000, status="unread"))
    p = db.latest_profile()
    paused = db.get_state("paused", False)
    _, plan = scheduler.todays_plan()
    pending = [s["at"][11:16] for s in plan if not s["done"]]
    return say(
        f"{n} saved, {unread} unread. profile built from {p['item_count'] if p else 0} items. "
        f"{'paused' if paused else 'active'}. today's drops left: {', '.join(pending) or 'none'}."
    )


HELP = (
    "send me links (articles, tweets, reddit, tiktok, youtube, goodreads), screenshots, or just a "
    "book title or thought. i read them, keep them, and text you bits back a few times a day.\n\n"
    "words i understand: taste, hit me, more, read, status, pause, resume. anything else and we just talk."
)


def handle_message(m):
    text = m["text"]
    note_text = text
    urls = imessage.extract_urls(text)
    images = [a for a in m["attachments"] if a["mime"].startswith("image/") or a["path"].lower().endswith((".heic", ".jpg", ".jpeg", ".png", ".webp"))]

    if urls:
        for url in urls[:3]:
            note = imessage.URL_RE.sub("", note_text).strip()
            try:
                _, ack = ingest_url(url, note=note, msg_rowid=m["rowid"])
                say(ack)
            except Exception as e:
                log.error("ingest failed for %s: %s\n%s", url, e, traceback.format_exc())
                db.add_item(url=url, kind="link", title=url, note=note or None, msg_rowid=m["rowid"],
                            summary="(pending)", snippets=[], tags=[], status="pending")
                say(failure_ack(e))
        return

    if images:
        for att in images[:2]:
            try:
                _, ack = ingest_image(att["path"], note=text, msg_rowid=m["rowid"])
                if ack:
                    say(ack)
            except Exception as e:
                log.error("image ingest failed: %s\n%s", e, traceback.format_exc())
                say("couldn't read that image.")
        return

    if not text:
        return
    cmd = command_for(text)
    if cmd == "pause":
        db.set_state("paused", True); return say("paused. say resume when you want me back.")
    if cmd == "resume":
        db.set_state("paused", False); return say("back.")
    if cmd == "profile":
        return do_profile()
    if cmd == "surface":
        return do_surface()
    if cmd == "more":
        return do_more()
    if cmd == "read":
        last = db.last_surface()
        if last and last.get("item_id"):
            db.update_item(last["item_id"], status="read")
            return say("marked read.")
        return say("nothing to mark.")
    if cmd == "status":
        return do_status()
    if cmd == "help":
        return say(HELP)
    reply = brain.chat(text)
    if reply:
        say(reply)


# ---- loop ------------------------------------------------------------------

def process_new_messages():
    since = db.get_state("last_rowid")
    if since is None:
        since = imessage.max_rowid()
        db.set_state("last_rowid", since)
        log.info("cursor initialised at rowid %s", since)
        return
    msgs = imessage.fetch_new(since)
    if not msgs:
        return
    echoes = db.recent_sent_texts()
    for m in msgs:
        db.set_state("last_rowid", m["rowid"])
        if m["text"].strip() in echoes:
            continue  # our own reply landing in the self chat
        if time.time() - m["ts"] > 6 * 3600:
            log.info("skipping stale message %s", m["rowid"])
            continue
        log.info("incoming %s: %s%s", m["rowid"], m["text"][:100], f" [+{len(m['attachments'])} att]" if m["attachments"] else "")
        try:
            handle_message(m)
        except Exception as e:
            log.error("handle failed: %s\n%s", e, traceback.format_exc())


def maybe_surface():
    due = scheduler.due_slot()
    if not due:
        return
    key, i = due
    scheduler.mark_slot_done(key, i)
    if db.count_items() == 0:
        return
    do_surface()


def maybe_refresh_profile():
    n = db.get_state("items_since_profile", 0) or 0
    if n == 0:
        return
    p = db.latest_profile()
    stale = (not p) or (time.time() - p["created_at"] > PROFILE_MAX_AGE_HOURS * 3600)
    if n >= PROFILE_REFRESH_EVERY or stale:
        log.info("refreshing profile (%s new items)", n)
        brain.refresh_profile()
        db.set_state("items_since_profile", 0)


def wait_for_permissions():
    """Under launchd the python binary needs Full Disk Access to read chat.db.
    Don't crash-loop; log the fix once a minute and keep waiting."""
    import sqlite3, sys, os
    while True:
        try:
            imessage.max_rowid()
            return
        except sqlite3.OperationalError as e:
            real = os.path.realpath(sys.executable)
            log.error("cannot read chat.db (%s). grant Full Disk Access to: %s  "
                      "(System Settings > Privacy & Security > Full Disk Access, press + , "
                      "cmd+shift+G, paste the path). retrying in 60s.", e, real)
            time.sleep(60)


def run():
    setup_logging()
    db.init()
    wait_for_permissions()
    log.info("taste daemon up. self chats: %s", imessage.self_chat_ids())
    while True:
        for step in (process_new_messages, retry_pending, maybe_surface, maybe_refresh_profile):
            try:
                step()
            except Exception as e:
                log.error("%s crashed: %s\n%s", step.__name__, e, traceback.format_exc())
        time.sleep(POLL_SECONDS)
