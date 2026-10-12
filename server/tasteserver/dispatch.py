"""Hosted outbound delivery with bounded retries and per-bubble idempotency."""

import logging
import time

import httpx

from . import blooio, db, memory
from .scheduler import _now

log = logging.getLogger("taste.dispatch")
MAX_ATTEMPTS = 5


def _phone_for(user_id):
    r = db.q(
        "SELECT address FROM handles WHERE user_id = %s AND address LIKE '+%%' ORDER BY last_seen_at DESC NULLS LAST LIMIT 1",
        (user_id,),
        one=True,
    )
    return r["address"] if r else None


def _chat_for(user_id, meta):
    if meta.get("chat_id"):
        return meta["chat_id"]
    last = db.last_inbound(user_id)
    return last["chat_id"] if last and last.get("chat_id") else None


def retry_delay(error, attempt):
    if attempt >= MAX_ATTEMPTS:
        return None
    if isinstance(error, blooio.SendError):
        if not error.retryable:
            return None
        delay = max(15 * 2 ** (attempt - 1), error.retry_after or 0)
        # Don't replay beyond the provider's idempotency retention window.
        return delay if delay <= 3600 else None
    if isinstance(error, httpx.TransportError):
        return 15 * 2 ** (attempt - 1)
    return None


def _claim():
    # A lost worker lease can be recovered safely for texts using the stored send plan.
    # Reactions lack that guarantee, so abandoned reactions require manual attention.
    db.q(
        """UPDATE messages SET status = CASE WHEN kind = 'reaction' OR send_attempts >= %s
              OR send_locked_at < now() - interval '12 hours' THEN 'failed' ELSE 'queued' END,
              send_locked_at = NULL, meta = meta || '{"error": "worker interrupted during send"}'
              WHERE status = 'sending' AND send_locked_at < now() - interval '5 minutes'""",
        (MAX_ATTEMPTS,),
    )
    return db.q(
        """UPDATE messages SET status = 'sending', send_locked_at = now(), send_attempts = send_attempts + 1
                   WHERE id = (
                     SELECT m.id FROM messages m JOIN users u ON u.id = m.user_id
                     WHERE m.direction = 'out' AND m.status = 'queued' AND m.send_after <= now()
                       AND u.transport = 'blooio' AND u.status = 'active'
                       AND NOT EXISTS (SELECT 1 FROM messages earlier WHERE earlier.user_id = m.user_id
                         AND earlier.direction = 'out' AND earlier.id < m.id AND earlier.status IN ('queued', 'sending'))
                     ORDER BY m.id FOR UPDATE OF m SKIP LOCKED LIMIT 1)
                   RETURNING *""",
        one=True,
    )


def _send(m):
    meta = m["meta"] or {}
    if meta.get("proactive"):
        user = db.get_user(m["user_id"])
        now = _now(user)
        item = db.get_item(m["user_id"], meta.get("item_id"))
        # Recheck immediately before transport; a pause or quiet hour can happen while queued.
        allowed = (
            not (user.get("settings") or {}).get("paused")
            and int(db.user_setting(user, "surfaces_per_day")) > 0
            and int(db.user_setting(user, "wake_start")) <= now.hour < int(db.user_setting(user, "wake_end"))
            and (now - m["created_at"]).total_seconds() < 7200
            and item
            and memory.eligible(item)
        )
        if not allowed:
            db.q("UPDATE messages SET status='cancelled', send_locked_at=NULL WHERE id=%s", (m["id"],))
            return
    if meta.get("login_challenge"):
        live = db.q(
            "SELECT 1 FROM login_challenges WHERE id = %s AND used_at IS NULL AND expires_at > now()",
            (meta["login_challenge"],),
            one=True,
        )
        if not live:
            db.q("UPDATE messages SET status = 'cancelled', send_locked_at = NULL WHERE id = %s", (m["id"],))
            return
    if m["kind"] == "reaction":
        ok = blooio.react(
            meta.get("chat_id") or _chat_for(m["user_id"], meta), meta.get("target_external_id"), meta.get("reaction")
        )
        db.q(
            "UPDATE messages SET status = %s, sent_at = now(), send_locked_at = NULL WHERE id = %s",
            ("sent" if ok else "failed", m["id"]),
        )
        return
    plan = meta.get("send_plan")
    if plan is None:
        to = meta.get("to") or _phone_for(m["user_id"])
        if not to:
            raise ValueError("no phone handle")
        plan = {"to": to, "from": blooio.NUMBER, "bubbles": blooio.split_bubbles(m["text"] or "")}
        db.q("UPDATE messages SET meta = meta || %s WHERE id = %s", (db.J({"send_plan": plan}), m["id"]))
    chat_id = _chat_for(m["user_id"], meta)
    last = meta.get("last_send") or {}
    for i in range(int(meta.get("next_bubble", 0)), len(plan["bubbles"])):
        b = plan["bubbles"][i]
        if chat_id:
            blooio.typing(chat_id, True)
            time.sleep(min(0.6 + len(b) / 120, 3.0))
        last = blooio.send_text(
            plan["to"], b, from_number=plan["from"], idempotency_key=f"taste:{m['user_id']}:{m['id']}:{i}"
        )
        chat_id = chat_id or last.get("chat_id")
        # A crash before this checkpoint replays the identical key and body.
        db.q(
            "UPDATE messages SET meta = meta || %s WHERE id = %s",
            (
                db.J(
                    {
                        "next_bubble": i + 1,
                        "last_send": {k: last.get(k) for k in ("id", "message_id", "protocol", "status")},
                        "chat_id": chat_id,
                    }
                ),
                m["id"],
            ),
        )
    db.q(
        """UPDATE messages SET status = 'sent', sent_at = now(), send_locked_at = NULL,
             external_id = %s, chat_id = %s, meta = (meta - 'error') || %s WHERE id = %s""",
        (
            last.get("id") or last.get("message_id"),
            chat_id,
            db.J(
                {
                    "bubbles": len(plan["bubbles"]),
                    "protocol": last.get("protocol"),
                    "provider_status": last.get("status"),
                }
            ),
            m["id"],
        ),
    )


def run_once():
    if not blooio.enabled():
        return 0
    n = 0
    for _ in range(20):
        m = _claim()
        if not m:
            break
        try:
            _send(m)
            n += 1
        except Exception as e:
            delay = retry_delay(e, m["send_attempts"]) if m["kind"] != "reaction" else None
            log.warning("send %s attempt %s: %s", m["id"], m["send_attempts"], type(e).__name__)
            db.q(
                """UPDATE messages SET status = %s, send_after = now() + make_interval(secs => %s),
                     send_locked_at = NULL, meta = meta || %s WHERE id = %s""",
                (
                    "queued" if delay is not None else "failed",
                    delay or 0,
                    db.J({"error": str(e)[:300], "retryable": delay is not None}),
                    m["id"],
                ),
            )
    return n
