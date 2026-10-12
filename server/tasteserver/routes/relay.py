"""The relay transport API: anything that can post inbound texts and poll for outbound ones.

A relay authenticates with a transport-scoped key and may only speak for handles registered to that key's user.
"""

import base64
import binascii
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, ratelimit, storage
from ..auth import TRANSPORT, Principal, target_user
from ..config import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS
from .common import IMAGE_TYPES, key_rate_limit

router = APIRouter()


class Attachment(BaseModel):
    name: str = "file"
    content_type: str
    data_b64: str


class Inbound(BaseModel):
    handle: str
    text: str = ""
    kind: str = "text"  # text | reaction
    reaction: str | None = None  # love|like|dislike|laugh|emphasize|question
    target_external_id: str | None = None
    external_id: str | None = None
    ts: float | None = None
    attachments: list[Attachment] = Field(default_factory=list)


def _handle_for(p: Principal, address):
    h = db.q("SELECT * FROM handles WHERE address = %s", (address,), one=True)
    if not h or (not p.is_admin() and h["user_id"] != p.user_id):
        raise HTTPException(403, "handle not registered to this key's user")
    return h


@router.post("/v1/inbound")
def inbound(body: Inbound, p: Principal = TRANSPORT):
    key_rate_limit(p)
    h = _handle_for(p, body.handle)
    uid = h["user_id"]
    user = db.get_user(uid)
    if user["status"] != "active":
        raise HTTPException(403, "user disabled")
    ratelimit.hit(f"inbound_h:{uid}", int(db.setting("rate_inbound_per_hour")), 3600)
    ratelimit.hit(f"inbound_d:{uid}", int(db.setting("rate_inbound_per_day")), 86400)
    if len(body.attachments) > MAX_ATTACHMENTS:
        raise HTTPException(413, "too many attachments")
    if body.external_id and db.q(
        "SELECT 1 FROM messages WHERE user_id = %s AND direction = 'in' AND external_id = %s", (uid, body.external_id)
    ):
        return {"ok": True, "duplicate": True}
    stored = []
    msg_key = uuid.uuid4().hex[:12]
    for i, a in enumerate(body.attachments):
        ct = a.content_type.split(";")[0].strip().lower()
        if ct not in IMAGE_TYPES:
            continue
        try:
            data = base64.b64decode(a.data_b64, validate=True)
        except binascii.Error:
            raise HTTPException(400, "attachment is not valid base64") from None
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, "attachment too large")
        key = f"users/{uid}/in/{msg_key}/{i}.{IMAGE_TYPES[ct]}"
        storage.put(key, data, ct)
        stored.append({"key": key, "content_type": ct, "bytes": len(data), "name": a.name[:80]})
    meta = {}
    if body.kind == "reaction":
        meta = {"reaction": body.reaction, "target_external_id": body.target_external_id}
    m = db.q(
        """INSERT INTO messages(user_id, direction, handle_id, text, kind, attachments, external_id, status, meta)
                VALUES (%s, 'in', %s, %s, %s, %s, %s, 'received', %s) RETURNING id""",
        (uid, h["id"], body.text[:8000], body.kind, db.J(stored), body.external_id, db.J(meta)),
        one=True,
    )
    db.q("UPDATE handles SET last_seen_at = now() WHERE id = %s", (h["id"],))
    job = db.enqueue(uid, "handle_message", {"message_id": m["id"]})
    return {"ok": True, "message_id": m["id"], "job_id": job}


class Hello(BaseModel):
    handle: str
    capabilities: list[str] = Field(default_factory=list)  # react, typing, effects


@router.post("/v1/transport/hello")
def transport_hello(body: Hello, p: Principal = TRANSPORT):
    h = _handle_for(p, body.handle)
    caps = [c for c in body.capabilities if c in ("react", "typing", "effects")]
    db.q("UPDATE handles SET capabilities = %s, last_seen_at = now() WHERE id = %s", (db.J(caps), h["id"]))
    return {"ok": True, "capabilities": caps}


@router.get("/v1/outbound")
def outbound(request: Request, p: Principal = TRANSPORT):
    key_rate_limit(p)
    u = target_user(request, p)
    if u.get("transport") != "relay":
        return {"messages": []}
    rows = db.q(
        "SELECT id, kind, text, meta, created_at FROM messages WHERE user_id = %s AND direction = 'out' AND status = 'queued' ORDER BY id LIMIT 20",
        (u["id"],),
    )
    return {"messages": [dict(r) for r in rows]}


class Ack(BaseModel):
    external_id: str | None = None
    ok: bool = True
    error: str | None = None


@router.post("/v1/outbound/{mid}/ack")
def ack(mid: int, body: Ack, request: Request, p: Principal = TRANSPORT):
    u = target_user(request, p)
    status = "sent" if body.ok else "failed"
    r = db.q(
        "UPDATE messages SET status = %s, sent_at = now(), external_id = COALESCE(%s, external_id), meta = meta || %s WHERE id = %s AND user_id = %s AND direction = 'out' RETURNING id",
        (status, body.external_id, db.J({"error": body.error} if body.error else {}), mid, u["id"]),
        one=True,
    )
    if not r:
        raise HTTPException(404, "no such outbound message")
    return {"ok": True}
