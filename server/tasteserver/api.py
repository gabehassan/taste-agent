"""HTTP API. Every route except /health requires a bearer key."""
import base64
import hashlib
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auth, db, ratelimit, storage
from .auth import Principal, require, target_user
from .config import DASHBOARD_ORIGIN, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS, MAX_BODY_BYTES
from .connections import TYPES as CONNECTION_TYPES

log = logging.getLogger("taste.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def bootstrap():
    """First boot: create the admin key from ADMIN_BOOTSTRAP_KEY if no keys exist yet."""
    raw = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
    if not raw or not raw.startswith("tk_"):
        return
    if db.q("SELECT 1 FROM api_keys LIMIT 1"):
        return
    h = hashlib.sha256(raw.encode()).hexdigest()
    db.q("INSERT INTO api_keys(user_id, name, key_hash, prefix, scopes) VALUES (NULL, 'bootstrap admin', %s, %s, %s)",
         (h, raw[:10], ["admin"]))
    log.info("bootstrap admin key created")


@asynccontextmanager
async def lifespan(app):
    db.migrate()
    bootstrap()
    yield


app = FastAPI(title="taste api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
if DASHBOARD_ORIGIN:
    app.add_middleware(CORSMiddleware, allow_origins=[DASHBOARD_ORIGIN], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path != "/health":
        cl = request.headers.get("content-length")
        if cl and int(cl) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "body too large"}, 413)
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
        try:
            ratelimit.hit(f"ip:{ip}", int(db.setting("rate_ip_per_min")), 60)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, 429, headers=e.headers)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/health")
def health():
    return {"ok": True}


def _key_rate(p: Principal):
    ratelimit.hit(f"key:{p.key_id}", int(db.setting("rate_key_per_hour")), 3600)


def _clean(row):
    if row is None:
        return None
    d = dict(row); d.pop("tsv", None); d.pop("key_hash", None)
    return d


# =============================================================================
# transport: inbound / outbound
# =============================================================================

class Attachment(BaseModel):
    name: str = "file"
    content_type: str
    data_b64: str


class Inbound(BaseModel):
    handle: str
    text: str = ""
    kind: str = "text"                     # text | reaction
    reaction: Optional[str] = None         # love|like|dislike|laugh|emphasize|question
    target_external_id: Optional[str] = None
    external_id: Optional[str] = None
    ts: Optional[float] = None
    attachments: list[Attachment] = Field(default_factory=list)


def _handle_for(p: Principal, address):
    h = db.q("SELECT * FROM handles WHERE address = %s", (address,), one=True)
    if not h or (not p.is_admin() and h["user_id"] != p.user_id):
        raise HTTPException(403, "handle not registered to this key's user")
    return h


@app.post("/v1/inbound")
def inbound(body: Inbound, p: Principal = Depends(require("transport"))):
    _key_rate(p)
    h = _handle_for(p, body.handle)
    uid = h["user_id"]
    user = db.get_user(uid)
    if user["status"] != "active":
        raise HTTPException(403, "user disabled")
    ratelimit.hit(f"inbound_h:{uid}", int(db.setting("rate_inbound_per_hour")), 3600)
    ratelimit.hit(f"inbound_d:{uid}", int(db.setting("rate_inbound_per_day")), 86400)
    if len(body.attachments) > MAX_ATTACHMENTS:
        raise HTTPException(413, "too many attachments")
    if body.external_id and db.q("SELECT 1 FROM messages WHERE user_id = %s AND direction = 'in' AND external_id = %s", (uid, body.external_id)):
        return {"ok": True, "duplicate": True}
    stored = []
    msg_key = uuid.uuid4().hex[:12]
    for i, a in enumerate(body.attachments):
        if not a.content_type.startswith("image/"):
            continue
        data = base64.b64decode(a.data_b64)
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, "attachment too large")
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(a.content_type, "bin")
        key = f"users/{uid}/in/{msg_key}/{i}.{ext}"
        storage.put(key, data, a.content_type)
        stored.append({"key": key, "content_type": a.content_type, "bytes": len(data), "name": a.name[:80]})
    meta = {}
    if body.kind == "reaction":
        meta = {"reaction": body.reaction, "target_external_id": body.target_external_id}
    m = db.q("""INSERT INTO messages(user_id, direction, handle_id, text, kind, attachments, external_id, status, meta)
                VALUES (%s, 'in', %s, %s, %s, %s, %s, 'received', %s) RETURNING id""",
             (uid, h["id"], body.text[:8000], body.kind, db.J(stored), body.external_id, db.J(meta)), one=True)
    db.q("UPDATE handles SET last_seen_at = now() WHERE id = %s", (h["id"],))
    job = db.enqueue(uid, "handle_message", {"message_id": m["id"]})
    return {"ok": True, "message_id": m["id"], "job_id": job}


class Hello(BaseModel):
    handle: str
    capabilities: list[str] = Field(default_factory=list)   # react, typing, effects


@app.post("/v1/transport/hello")
def transport_hello(body: Hello, p: Principal = Depends(require("transport"))):
    h = _handle_for(p, body.handle)
    caps = [c for c in body.capabilities if c in ("react", "typing", "effects")]
    db.q("UPDATE handles SET capabilities = %s, last_seen_at = now() WHERE id = %s", (db.J(caps), h["id"]))
    return {"ok": True, "capabilities": caps}


@app.get("/v1/outbound")
def outbound(request: Request, p: Principal = Depends(require("transport"))):
    _key_rate(p)
    u = target_user(request, p)
    rows = db.q("SELECT id, kind, text, meta, created_at FROM messages WHERE user_id = %s AND direction = 'out' AND status = 'queued' ORDER BY id LIMIT 20", (u["id"],))
    return {"messages": [dict(r) for r in rows]}


class Ack(BaseModel):
    external_id: Optional[str] = None
    ok: bool = True
    error: Optional[str] = None


@app.post("/v1/outbound/{mid}/ack")
def ack(mid: int, body: Ack, request: Request, p: Principal = Depends(require("transport"))):
    u = target_user(request, p)
    status = "sent" if body.ok else "failed"
    r = db.q("UPDATE messages SET status = %s, sent_at = now(), external_id = COALESCE(%s, external_id), meta = meta || %s WHERE id = %s AND user_id = %s AND direction = 'out' RETURNING id",
             (status, body.external_id, db.J({"error": body.error} if body.error else {}), mid, u["id"]), one=True)
    if not r:
        raise HTTPException(404, "no such outbound message")
    return {"ok": True}


# =============================================================================
# user-scoped
# =============================================================================

@app.get("/v1/me")
def me(request: Request, p: Principal = Depends(require("user", "transport"))):
    u = target_user(request, p)
    return {"user": _clean(u), "scopes": sorted(p.scopes), "spend_today": db.spend(u["id"], 1)}


@app.get("/v1/items")
def items(request: Request, limit: int = 50, offset: int = 0, status: Optional[str] = None, kind: Optional[str] = None,
          q: Optional[str] = None, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    limit = min(limit, 200)
    rows = db.search_items(u["id"], q, limit) if q else db.list_items(u["id"], limit, status, offset, kind)
    return {"items": [_clean(r) for r in rows], "total": db.count_items(u["id"])}


@app.get("/v1/items/{item_id}")
def item(item_id: int, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    it = db.get_item(u["id"], item_id)
    if not it:
        raise HTTPException(404)
    d = _clean(it)
    d["media_urls"] = [storage.presign(m["key"]) for m in (it.get("media") or []) if m.get("key")]
    return d


class ItemPatch(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
    tags: Optional[list[str]] = None


@app.patch("/v1/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    if not db.get_item(u["id"], item_id):
        raise HTTPException(404)
    f = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in f and f["status"] not in ("unread", "read", "archived"):
        raise HTTPException(400, "bad status")
    if f:
        db.update_item(item_id, **f)
    return _clean(db.get_item(u["id"], item_id))


@app.delete("/v1/items/{item_id}")
def delete_item(item_id: int, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    it = db.get_item(u["id"], item_id)
    if not it:
        raise HTTPException(404)
    for m in it.get("media") or []:
        try:
            storage.delete(m["key"])
        except Exception:
            pass
    db.q("DELETE FROM items WHERE id = %s", (item_id,))
    return {"ok": True}


class IngestBody(BaseModel):
    url: str
    note: str = ""
    notify: bool = False


@app.post("/v1/items/ingest")
def ingest(body: IngestBody, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    ok, why = db.spend_ok(u)
    if not ok:
        raise HTTPException(402, f"spend cap: {why}")
    ratelimit.hit(f"ingest:{u['id']}", int(db.setting("rate_ingest_per_day")), 86400)
    job = db.enqueue(u["id"], "ingest_url", {"url": body.url, "note": body.note, "notify": body.notify})
    return {"job_id": job}


@app.get("/v1/profile")
def profile(request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    return {"profile": _clean(db.latest_profile(u["id"])), "history": [{"id": r["id"], "created_at": r["created_at"], "item_count": r["item_count"]}
                                                                   for r in db.q("SELECT id, created_at, item_count FROM profiles WHERE user_id = %s ORDER BY id DESC LIMIT 20", (u["id"],))]}


@app.post("/v1/profile/refresh")
def profile_refresh(request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    ok, why = db.spend_ok(u)
    if not ok:
        raise HTTPException(402, f"spend cap: {why}")
    return {"job_id": db.enqueue(u["id"], "refresh_profile")}


@app.post("/v1/surface")
def surface_now(request: Request, kind: Optional[str] = None, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    return {"job_id": db.enqueue(u["id"], "surface", {"kind": kind})}


@app.get("/v1/surfaces")
def surfaces(request: Request, limit: int = 50, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    return {"surfaces": db.q("SELECT * FROM surfaces WHERE user_id = %s ORDER BY id DESC LIMIT %s", (u["id"], min(limit, 200)))}


@app.get("/v1/messages")
def messages(request: Request, limit: int = 50, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    return {"messages": db.q("SELECT id, direction, kind, text, status, attachments, meta, created_at, sent_at FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT %s", (u["id"], min(limit, 200)))}


# ---- connections ---------------------------------------------------------------

@app.get("/v1/connections")
def connections(request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    return {"connections": db.q("SELECT * FROM connections WHERE user_id = %s ORDER BY created_at", (u["id"],)), "types": CONNECTION_TYPES}


class ConnectionBody(BaseModel):
    type: str
    config: dict


@app.post("/v1/connections")
def add_connection(body: ConnectionBody, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    if body.type not in CONNECTION_TYPES:
        raise HTTPException(400, "unknown connection type")
    need = CONNECTION_TYPES[body.type]["config"]
    cfg = {k: str(body.config.get(k, "")).strip()[:300] for k in need}
    if any(not v for v in cfg.values()):
        raise HTTPException(400, f"config needs: {', '.join(need)}")
    if body.type == "rss":
        from .netguard import check_url
        check_url(cfg["url"])
    if len(db.q("SELECT 1 FROM connections WHERE user_id = %s", (u["id"],))) >= 10:
        raise HTTPException(400, "too many connections")
    r = db.q("INSERT INTO connections(user_id, type, config) VALUES (%s, %s, %s) RETURNING *", (u["id"], body.type, db.J(cfg)), one=True)
    db.enqueue(u["id"], "sync_connection", {"connection_id": str(r["id"])})
    db.audit(p.key_id, u["id"], "connection.add", {"type": body.type})
    return dict(r)


@app.post("/v1/connections/{cid}/sync")
def sync_connection(cid: str, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    if not db.q("SELECT 1 FROM connections WHERE id = %s AND user_id = %s", (cid, u["id"])):
        raise HTTPException(404)
    ratelimit.hit(f"sync:{cid}", 6, 3600)
    return {"job_id": db.enqueue(u["id"], "sync_connection", {"connection_id": cid})}


@app.delete("/v1/connections/{cid}")
def delete_connection(cid: str, request: Request, p: Principal = Depends(require("user"))):
    u = target_user(request, p)
    db.q("DELETE FROM connections WHERE id = %s AND user_id = %s", (cid, u["id"]))
    db.audit(p.key_id, u["id"], "connection.delete", {"id": cid})
    return {"ok": True}


# =============================================================================
# admin
# =============================================================================

@app.get("/v1/admin/overview")
def overview(p: Principal = Depends(require("admin"))):
    return {
        "users": db.q("SELECT COUNT(*) AS n FROM users", one=True)["n"],
        "items": db.q("SELECT COUNT(*) AS n FROM items", one=True)["n"],
        "jobs": {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")},
        "spend": {"today": db.spend(None, 1), "month": db.spend(None, 30)},
        "caps": {"global_daily": db.setting("global_daily_cap_usd"), "global_monthly": db.setting("global_monthly_cap_usd")},
        "messages_24h": {r["direction"]: r["n"] for r in db.q("SELECT direction, COUNT(*) AS n FROM messages WHERE created_at > now() - interval '1 day' GROUP BY direction")},
        "storage": _storage_usage_cached(),
    }


_storage_cache = {"at": 0, "v": None}


def _storage_usage_cached():
    import time
    if time.time() - _storage_cache["at"] > 600:
        try:
            _storage_cache["v"] = storage.usage()
        except Exception as e:
            _storage_cache["v"] = {"error": str(e)[:100]}
        _storage_cache["at"] = time.time()
    return _storage_cache["v"]


@app.get("/v1/admin/users")
def admin_users(p: Principal = Depends(require("admin"))):
    rows = db.q("""SELECT u.*, (SELECT COUNT(*) FROM items i WHERE i.user_id = u.id) AS items,
                   (SELECT json_agg(json_build_object('id', h.id, 'kind', h.kind, 'address', h.address, 'capabilities', h.capabilities, 'last_seen_at', h.last_seen_at)) FROM handles h WHERE h.user_id = u.id) AS handles,
                   (SELECT json_agg(json_build_object('id', k.id, 'name', k.name, 'prefix', k.prefix, 'scopes', k.scopes, 'last_used_at', k.last_used_at, 'revoked_at', k.revoked_at)) FROM api_keys k WHERE k.user_id = u.id) AS keys
                   FROM users u ORDER BY u.created_at""")
    out = []
    for r in rows:
        d = dict(r); d["spend_today"] = db.spend(r["id"], 1); d["spend_month"] = db.spend(r["id"], 30); out.append(d)
    return {"users": out}


class UserBody(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    role: str = "user"
    tz: str = "America/Detroit"
    handles: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)


@app.post("/v1/admin/users")
def create_user(body: UserBody, p: Principal = Depends(require("admin"))):
    r = db.q("INSERT INTO users(email, name, role, tz, settings) VALUES (%s, %s, %s, %s, %s) RETURNING *",
             (body.email, body.name, body.role if body.role in ("user", "admin") else "user", body.tz, db.J(body.settings)), one=True)
    for h in body.handles:
        db.q("INSERT INTO handles(user_id, kind, address) VALUES (%s, 'imessage', %s) ON CONFLICT DO NOTHING", (r["id"], h.strip()))
    db.audit(p.key_id, r["id"], "user.create", {"email": body.email})
    return _clean(r)


class UserPatch(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    tz: Optional[str] = None
    settings: Optional[dict] = None


@app.patch("/v1/admin/users/{uid}")
def patch_user(uid: str, body: UserPatch, p: Principal = Depends(require("admin"))):
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404)
    f = {k: v for k, v in body.model_dump().items() if v is not None}
    if "settings" in f:
        db.q("UPDATE users SET settings = settings || %s WHERE id = %s", (db.J(f.pop("settings")), uid))
    if f:
        sets = ", ".join(f"{k} = %s" for k in f)
        db.q(f"UPDATE users SET {sets} WHERE id = %s", (*f.values(), uid))
    db.audit(p.key_id, uid, "user.patch", body.model_dump(exclude_none=True))
    return _clean(db.get_user(uid))


class HandleBody(BaseModel):
    address: str
    kind: str = "imessage"


@app.post("/v1/admin/users/{uid}/handles")
def add_handle(uid: str, body: HandleBody, p: Principal = Depends(require("admin"))):
    r = db.q("INSERT INTO handles(user_id, kind, address) VALUES (%s, %s, %s) RETURNING *", (uid, body.kind, body.address.strip()), one=True)
    db.audit(p.key_id, uid, "handle.add", {"address": body.address})
    return dict(r)


@app.delete("/v1/admin/handles/{hid}")
def delete_handle(hid: str, p: Principal = Depends(require("admin"))):
    db.q("DELETE FROM handles WHERE id = %s", (hid,))
    return {"ok": True}


class KeyBody(BaseModel):
    name: str = "key"
    scopes: list[str] = Field(default_factory=lambda: ["transport"])


@app.post("/v1/admin/users/{uid}/keys")
def create_key(uid: str, body: KeyBody, p: Principal = Depends(require("admin"))):
    scopes = [s for s in body.scopes if s in auth.SCOPES]
    if not scopes:
        raise HTTPException(400, "no valid scopes")
    if not db.get_user(uid):
        raise HTTPException(404)
    raw, kid = auth.create_key(uid, body.name, scopes)
    db.audit(p.key_id, uid, "key.create", {"name": body.name, "scopes": scopes})
    return {"key": raw, "id": kid, "scopes": scopes, "note": "shown once; store it now"}


@app.delete("/v1/admin/keys/{kid}")
def revoke_key(kid: str, p: Principal = Depends(require("admin"))):
    db.q("UPDATE api_keys SET revoked_at = now() WHERE id = %s", (kid,))
    db.audit(p.key_id, None, "key.revoke", {"id": kid})
    return {"ok": True}


@app.get("/v1/admin/usage")
def admin_usage(days: int = 30, p: Principal = Depends(require("admin"))):
    days = min(days, 365)
    return {
        "by_day": db.q("SELECT date_trunc('day', created_at) AS day, SUM(cost_usd) AS cost, COUNT(*) AS calls FROM usage WHERE created_at > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 1", (days,)),
        "by_user": db.q("SELECT u.id, u.name, u.email, SUM(g.cost_usd) AS cost, COUNT(*) AS calls FROM usage g JOIN users u ON u.id = g.user_id WHERE g.created_at > now() - make_interval(days => %s) GROUP BY 1, 2, 3 ORDER BY cost DESC", (days,)),
        "by_model": db.q("SELECT model, kind, SUM(cost_usd) AS cost, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(seconds) AS seconds, COUNT(*) AS calls FROM usage WHERE created_at > now() - make_interval(days => %s) GROUP BY 1, 2 ORDER BY cost DESC", (days,)),
    }


@app.get("/v1/admin/settings")
def get_settings(p: Principal = Depends(require("admin"))):
    return {"settings": db.settings()}


@app.put("/v1/admin/settings")
def put_settings(body: dict, p: Principal = Depends(require("admin"))):
    from .config import DEFAULT_SETTINGS
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            raise HTTPException(400, f"unknown setting {k}")
        if isinstance(DEFAULT_SETTINGS[k], (int, float)) and not isinstance(v, (int, float)):
            raise HTTPException(400, f"{k} must be a number")
        db.set_setting(k, v)
    db.audit(p.key_id, None, "settings.put", body)
    return {"settings": db.settings()}


@app.get("/v1/admin/jobs")
def admin_jobs(limit: int = 100, status: Optional[str] = None, p: Principal = Depends(require("admin"))):
    if status:
        return {"jobs": db.q("SELECT * FROM jobs WHERE status = %s ORDER BY id DESC LIMIT %s", (status, min(limit, 500)))}
    return {"jobs": db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT %s", (min(limit, 500),))}


@app.post("/v1/admin/jobs/{jid}/retry")
def retry_job(jid: int, p: Principal = Depends(require("admin"))):
    db.q("UPDATE jobs SET status = 'queued', attempts = 0, run_after = now(), error = NULL WHERE id = %s", (jid,))
    return {"ok": True}


@app.get("/v1/admin/audit")
def admin_audit(limit: int = 100, p: Principal = Depends(require("admin"))):
    return {"audit": db.q("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 500),))}


@app.get("/v1/admin/messages")
def admin_messages(limit: int = 100, p: Principal = Depends(require("admin"))):
    return {"messages": db.q("SELECT m.id, m.user_id, u.name, m.direction, m.kind, m.text, m.status, m.meta, m.created_at, m.sent_at FROM messages m LEFT JOIN users u ON u.id = m.user_id ORDER BY m.id DESC LIMIT %s", (min(limit, 500),))}


class InviteBody(BaseModel):
    email: Optional[str] = None
    role: str = "user"
    days: int = 7


@app.post("/v1/admin/invites")
def create_invite(body: InviteBody, p: Principal = Depends(require("admin"))):
    tok = secrets.token_urlsafe(24)
    db.q("INSERT INTO invites(email, token_hash, role, expires_at, created_by) VALUES (%s, %s, %s, now() + make_interval(days => %s), %s)",
         (body.email, hashlib.sha256(tok.encode()).hexdigest(), body.role if body.role in ("user", "admin") else "user", min(body.days, 30), p.user_id))
    db.audit(p.key_id, None, "invite.create", {"email": body.email})
    return {"token": tok, "note": "shown once"}


@app.get("/v1/admin/invites")
def list_invites(p: Principal = Depends(require("admin"))):
    return {"invites": db.q("SELECT id, email, role, expires_at, used_at, created_at FROM invites ORDER BY created_at DESC LIMIT 100")}
