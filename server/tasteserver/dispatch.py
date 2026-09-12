"""Outbound dispatcher for hosted transports (Blooio). Runs inside the worker tick loop every few seconds."""
import logging
import time

from . import blooio, db

log = logging.getLogger("taste.dispatch")


def _phone_for(user_id):
    r = db.q("SELECT address FROM handles WHERE user_id = %s AND address LIKE '+%%' ORDER BY last_seen_at DESC NULLS LAST LIMIT 1", (user_id,), one=True)
    return r["address"] if r else None


def _chat_for(user_id, meta):
    if meta.get("chat_id"):
        return meta["chat_id"]
    last = db.last_inbound(user_id)
    return last["chat_id"] if last and last.get("chat_id") else None


def run_once():
    if not blooio.enabled():
        return 0
    rows = db.q("""SELECT m.* FROM messages m JOIN users u ON u.id = m.user_id
                   WHERE m.direction = 'out' AND m.status = 'queued' AND u.transport = 'blooio' ORDER BY m.id LIMIT 20""")
    n = 0
    for m in rows:
        # claim
        if not db.q("UPDATE messages SET status = 'sending' WHERE id = %s AND status = 'queued' RETURNING id", (m["id"],), one=True):
            continue
        meta = m["meta"] or {}
        try:
            if m["kind"] == "reaction":
                ok = blooio.react(meta.get("chat_id") or _chat_for(m["user_id"], meta), meta.get("target_external_id"), meta.get("reaction"))
                db.q("UPDATE messages SET status = %s, sent_at = now() WHERE id = %s", ("sent" if ok else "failed", m["id"]))
                n += 1
                continue
            to = _phone_for(m["user_id"])
            if not to:
                db.q("UPDATE messages SET status = 'failed', meta = meta || '{\"error\": \"no phone handle\"}' WHERE id = %s", (m["id"],))
                continue
            chat_id = _chat_for(m["user_id"], meta)
            bubbles = blooio.split_bubbles(m["text"] or "")
            last = None
            for i, b in enumerate(bubbles):
                if chat_id:
                    blooio.typing(chat_id, True)
                    time.sleep(min(0.6 + len(b) / 120, 3.0) if i == 0 else min(0.8 + len(b) / 90, 4.0))
                last = blooio.send_text(to, b)
                chat_id = chat_id or last.get("chat_id")
            db.q("UPDATE messages SET status = 'sent', sent_at = now(), external_id = %s, chat_id = %s, meta = meta || %s WHERE id = %s",
                 (last.get("id") if last else None, chat_id, db.J({"bubbles": len(bubbles), "protocol": (last or {}).get("protocol")}), m["id"]))
            n += 1
        except Exception as e:
            log.exception("dispatch failed for %s", m["id"])
            db.q("UPDATE messages SET status = 'failed', meta = meta || %s WHERE id = %s", (db.J({"error": str(e)[:300]}), m["id"]))
    return n
