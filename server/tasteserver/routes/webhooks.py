"""Blooio webhooks: a hosted iMessage number. Unknown senders are onboarded by invite unless open_signup is on."""
import hashlib
import json
import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import blooio, db, netguard, prompts, ratelimit, storage
from ..config import DEFAULT_TZ, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS
from .common import IMAGE_TYPES

log = logging.getLogger("taste.webhooks")
router = APIRouter()


def _store_remote_attachments(uid, atts):
    stored = []
    msg_key = uuid.uuid4().hex[:12]
    for i, a in enumerate(atts[:MAX_ATTACHMENTS]):
        try:
            r = netguard.get(a["url"], max_bytes=MAX_ATTACHMENT_BYTES, timeout=20)
            ct = (a.get("content_type") or r.headers.get("content-type", "")).split(";")[0].strip().lower()
            if ct not in IMAGE_TYPES:
                continue
            key = f"users/{uid}/in/{msg_key}/{i}.{IMAGE_TYPES[ct]}"
            storage.put(key, r.content, ct)
            stored.append({"key": key, "content_type": ct, "bytes": len(r.content), "name": a.get("name", "file")[:80]})
        except Exception as e:
            log.info("attachment fetch failed: %s", e)
    return stored


def _onboard_unknown(ev):
    """Someone new texted the number. Invite-only unless open_signup is on."""
    sender, text = ev["sender"], (ev.get("text") or "").strip()
    if not sender or ev["kind"] != "text":
        return
    if not ratelimit.check(f"unknown:{sender}", 5, 86400):
        return
    code = None
    m = re.search(r"\b([A-Za-z0-9_-]{16,})\b", text)
    if m:
        code = m.group(1)
    inv = None
    if code:
        inv = db.q("SELECT * FROM invites WHERE token_hash = %s AND used_at IS NULL AND expires_at > now() FOR UPDATE", (hashlib.sha256(code.encode()).hexdigest(),), one=True)
    if not inv and not db.setting("open_signup"):
        if ratelimit.check(f"unknown_reply:{sender}", 1, 86400):
            blooio.send_text(sender, prompts.copy("invite_only"), idempotency_key=f"invite-only:{sender}:{ev.get('event_id')}")
        return
    u = db.q("INSERT INTO users(name, email, role, tz, transport, onboarded_at) VALUES (%s, %s, %s, %s, 'blooio', now()) RETURNING *",
             (None, (inv or {}).get("email"), (inv or {}).get("role", "user"), DEFAULT_TZ), one=True)
    db.q("INSERT INTO handles(user_id, kind, address, capabilities, last_seen_at) VALUES (%s, 'imessage', %s, %s, now())",
         (u["id"], sender, db.J(["react", "typing"])))
    if inv:
        ev["text"] = text.replace(code, "", 1).strip()
        db.q("UPDATE invites SET used_at = now() WHERE id = %s", (inv["id"],))
    db.audit(None, u["id"], "user.onboard", {"via": "blooio", "invite": bool(inv)})
    db.queue_outbound(u["id"], prompts.copy("welcome"), meta={"chat_id": ev.get("chat_id")})
    return u


@router.post("/v1/webhooks/blooio")
async def blooio_webhook(request: Request):
    raw = await request.body()
    if not blooio.verify(raw, request.headers.get("x-blooio-signature", "")):
        raise HTTPException(401, "bad signature")
    evt = json.loads(raw or b"{}")
    return await run_in_threadpool(process_blooio_event, evt)


def process_blooio_event(evt):
    with db.transaction():
        return _process_blooio_event(evt)


def _process_blooio_event(evt):
    ev = blooio.parse_event(evt)
    if not ev:
        log.info("blooio event ignored: %s", evt.get("type"))
        return {"ok": True, "ignored": evt.get("type")}
    if not ev["sender"]:
        return {"ok": True, "ignored": "missing sender"}
    # Serialize a sender's onboarding and make the event receipt, message, and job atomic.
    db.q("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (ev["sender"],))
    eid = evt.get("id") or ev.get("message_id")
    if not eid:
        raise HTTPException(422, "missing event id")
    receipt = db.q("INSERT INTO webhook_events(id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id", (eid,), one=True)
    if not receipt:
        return {"ok": True, "duplicate": True}
    h = db.q("SELECT * FROM handles WHERE address = %s", (ev["sender"],), one=True)
    if not h:
        u = _onboard_unknown(ev)
        if not u:
            return {"ok": True, "unknown": True}
        h = db.q("SELECT * FROM handles WHERE address = %s", (ev["sender"],), one=True)
        # Preserve the first submission; only an invite token with no content ends here.
        if not ev.get("text") and not ev.get("attachments"):
            return {"ok": True, "onboarded": True}
    uid = h["user_id"]
    user = db.get_user(uid)
    if not user or user["status"] != "active":
        return {"ok": True, "inactive": True}
    if not ratelimit.check(f"inbound_h:{uid}", int(db.setting("rate_inbound_per_hour")), 3600) or \
       not ratelimit.check(f"inbound_d:{uid}", int(db.setting("rate_inbound_per_day")), 86400):
        return {"ok": True, "rate_limited": True}
    if user.get("transport") != "blooio":
        db.q("UPDATE users SET transport = 'blooio' WHERE id = %s", (uid,))
    db.q("UPDATE handles SET last_seen_at = now(), capabilities = %s WHERE id = %s", (db.J(["react", "typing"]), h["id"]))
    if ev["kind"] == "reaction":
        m = db.q("""INSERT INTO messages(user_id, direction, handle_id, text, kind, external_id, status, meta, chat_id)
                    VALUES (%s, 'in', %s, '', 'reaction', %s, 'received', %s, %s) RETURNING id""",
                 (uid, h["id"], ev["event_id"], db.J({"reaction": ev["reaction"], "target_external_id": ev.get("target_message_id")}), ev.get("chat_id")), one=True)
    else:
        if db.q("SELECT 1 FROM messages WHERE user_id = %s AND direction = 'in' AND external_id = %s", (uid, ev["message_id"])):
            return {"ok": True, "duplicate": True}
        stored = _store_remote_attachments(uid, ev["attachments"]) if ev["attachments"] else []
        m = db.q("""INSERT INTO messages(user_id, direction, handle_id, text, kind, attachments, external_id, status, chat_id)
                    VALUES (%s, 'in', %s, %s, 'text', %s, %s, 'received', %s) RETURNING id""",
                 (uid, h["id"], (ev["text"] or "")[:8000], db.J(stored), ev["message_id"], ev.get("chat_id")), one=True)
    job = db.enqueue(uid, "handle_message", {"message_id": m["id"]})
    return {"ok": True, "message_id": m["id"], "job_id": job}
