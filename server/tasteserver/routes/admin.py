"""Operator routes. Every write is recorded in the audit log."""

import hashlib
import secrets
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import auth, db, storage
from ..auth import ADMIN, Principal
from ..config import DEFAULT_SETTINGS, DEFAULT_TZ
from .common import check_tz, clean_row

router = APIRouter()


@router.get("/v1/admin/overview")
def overview(p: Principal = ADMIN):
    return {
        "users": db.q("SELECT COUNT(*) AS n FROM users", one=True)["n"],
        "items": db.q("SELECT COUNT(*) AS n FROM items", one=True)["n"],
        "jobs": {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")},
        "spend": {"today": db.spend(None, 1), "month": db.spend(None, 30)},
        "caps": {
            "global_daily": db.setting("global_daily_cap_usd"),
            "global_monthly": db.setting("global_monthly_cap_usd"),
        },
        "messages_24h": {
            r["direction"]: r["n"]
            for r in db.q(
                "SELECT direction, COUNT(*) AS n FROM messages WHERE created_at > now() - interval '1 day' GROUP BY direction"
            )
        },
        "storage": _storage_usage_cached(),
    }


_storage_cache = {"at": 0, "v": None}


def _storage_usage_cached():
    if time.time() - _storage_cache["at"] > 600:
        try:
            _storage_cache["v"] = storage.usage()
        except Exception as e:
            _storage_cache["v"] = {"error": str(e)[:100]}
        _storage_cache["at"] = time.time()
    return _storage_cache["v"]


@router.get("/v1/admin/users")
def admin_users(p: Principal = ADMIN):
    rows = db.q("""SELECT u.*, (SELECT COUNT(*) FROM items i WHERE i.user_id = u.id) AS items,
                   (SELECT json_agg(json_build_object('id', h.id, 'kind', h.kind, 'address', h.address, 'capabilities', h.capabilities, 'last_seen_at', h.last_seen_at)) FROM handles h WHERE h.user_id = u.id) AS handles,
                   (SELECT json_agg(json_build_object('id', k.id, 'name', k.name, 'prefix', k.prefix, 'scopes', k.scopes, 'last_used_at', k.last_used_at, 'revoked_at', k.revoked_at)) FROM api_keys k WHERE k.user_id = u.id) AS keys
                   FROM users u ORDER BY u.created_at""")
    out = []
    for r in rows:
        d = dict(r)
        d["spend_today"] = db.spend(r["id"], 1)
        d["spend_month"] = db.spend(r["id"], 30)
        out.append(d)
    return {"users": out}


class UserBody(BaseModel):
    email: str | None = None
    name: str | None = None
    role: str = "user"
    tz: str = DEFAULT_TZ
    handles: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)


@router.post("/v1/admin/users")
def create_user(body: UserBody, p: Principal = ADMIN):
    check_tz(body.tz)
    r = db.q(
        "INSERT INTO users(email, name, role, tz, settings) VALUES (%s, %s, %s, %s, %s) RETURNING *",
        (body.email, body.name, body.role if body.role in ("user", "admin") else "user", body.tz, db.J(body.settings)),
        one=True,
    )
    for h in body.handles:
        db.q(
            "INSERT INTO handles(user_id, kind, address) VALUES (%s, 'imessage', %s) ON CONFLICT DO NOTHING",
            (r["id"], h.strip()),
        )
    db.audit(p.key_id, r["id"], "user.create", {"email": body.email})
    return clean_row(r)


class UserPatch(BaseModel):
    name: str | None = None
    status: str | None = None
    role: str | None = None
    tz: str | None = None
    transport: str | None = None
    settings: dict | None = None


@router.patch("/v1/admin/users/{uid}")
def patch_user(uid: str, body: UserPatch, p: Principal = ADMIN):
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404)
    f = {k: v for k, v in body.model_dump().items() if v is not None}
    for field, allowed in (
        ("transport", ("relay", "blooio")),
        ("role", ("user", "admin")),
        ("status", ("active", "disabled")),
    ):
        if field in f and f[field] not in allowed:
            raise HTTPException(400, f"{field} must be one of: {', '.join(allowed)}")
    if "tz" in f:
        check_tz(f["tz"])
    if "settings" in f:
        db.q("UPDATE users SET settings = settings || %s WHERE id = %s", (db.J(f.pop("settings")), uid))
    if f:
        sets = ", ".join(f"{k} = %s" for k in f)
        db.q(f"UPDATE users SET {sets} WHERE id = %s", (*f.values(), uid))
    db.audit(p.key_id, uid, "user.patch", body.model_dump(exclude_none=True))
    return clean_row(db.get_user(uid))


class HandleBody(BaseModel):
    address: str
    kind: str = "imessage"


@router.post("/v1/admin/users/{uid}/handles")
def add_handle(uid: str, body: HandleBody, p: Principal = ADMIN):
    r = db.q(
        "INSERT INTO handles(user_id, kind, address) VALUES (%s, %s, %s) RETURNING *",
        (uid, body.kind, body.address.strip()),
        one=True,
    )
    db.audit(p.key_id, uid, "handle.add", {"address": body.address})
    return dict(r)


@router.delete("/v1/admin/handles/{hid}")
def delete_handle(hid: str, p: Principal = ADMIN):
    h = db.q("DELETE FROM handles WHERE id = %s RETURNING user_id, address", (hid,), one=True)
    if h:
        db.audit(p.key_id, h["user_id"], "handle.delete", {"address": h["address"]})
    return {"ok": True}


class KeyBody(BaseModel):
    name: str = "key"
    scopes: list[str] = Field(default_factory=lambda: ["transport"])


@router.post("/v1/admin/users/{uid}/keys")
def create_key(uid: str, body: KeyBody, p: Principal = ADMIN):
    scopes = [s for s in body.scopes if s in auth.SCOPES]
    if not scopes:
        raise HTTPException(400, "no valid scopes")
    if not db.get_user(uid):
        raise HTTPException(404)
    raw, kid = auth.create_key(uid, body.name, scopes)
    db.audit(p.key_id, uid, "key.create", {"name": body.name, "scopes": scopes})
    return {"key": raw, "id": kid, "scopes": scopes, "note": "shown once; store it now"}


@router.delete("/v1/admin/keys/{kid}")
def revoke_key(kid: str, p: Principal = ADMIN):
    db.q("UPDATE api_keys SET revoked_at = now() WHERE id = %s", (kid,))
    db.audit(p.key_id, None, "key.revoke", {"id": kid})
    return {"ok": True}


class ResetBody(BaseModel):
    profile: bool = True
    chat: bool = True
    surfaces: bool = True
    voice: bool = False
    items: bool = False


@router.post("/v1/admin/users/{uid}/reset")
def admin_reset(uid: str, body: ResetBody, p: Principal = ADMIN):
    """Wipe parts of a user's memory. Items only when explicitly asked."""
    if not db.get_user(uid):
        raise HTTPException(404)
    done = []
    if body.profile:
        db.q("DELETE FROM profiles WHERE user_id = %s", (uid,))
        done.append("profile")
    if body.chat:
        db.q("DELETE FROM chat_turns WHERE user_id = %s", (uid,))
        done.append("chat")
    if body.surfaces:
        db.q("DELETE FROM surfaces WHERE user_id = %s", (uid,))
        db.q("UPDATE items SET surfaced_count = 0, last_surfaced_at = NULL WHERE user_id = %s", (uid,))
        done.append("surfaces")
    if body.voice:
        db.q("UPDATE users SET state = state - 'voice' WHERE id = %s", (uid,))
        done.append("voice")
    if body.items:
        db.q("DELETE FROM items WHERE user_id = %s", (uid,))
        done.append("items")
    db.q(
        "UPDATE users SET state = (state - 'used_observations') || %s WHERE id = %s",
        (db.J({"items_since_profile": 0}), uid),
    )
    db.audit(p.key_id, uid, "user.reset", {"done": done})
    return {"ok": True, "reset": done}


@router.get("/v1/admin/usage")
def admin_usage(days: int = Query(30, ge=1, le=365), p: Principal = ADMIN):
    days = min(days, 365)
    return {
        "by_day": db.q(
            "SELECT date_trunc('day', created_at) AS day, SUM(cost_usd) AS cost, COUNT(*) AS calls FROM usage WHERE created_at > now() - make_interval(days => %s) GROUP BY 1 ORDER BY 1",
            (days,),
        ),
        "by_user": db.q(
            "SELECT u.id, u.name, u.email, SUM(g.cost_usd) AS cost, COUNT(*) AS calls FROM usage g JOIN users u ON u.id = g.user_id WHERE g.created_at > now() - make_interval(days => %s) GROUP BY 1, 2, 3 ORDER BY cost DESC",
            (days,),
        ),
        "by_model": db.q(
            "SELECT model, kind, SUM(cost_usd) AS cost, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(seconds) AS seconds, COUNT(*) AS calls FROM usage WHERE created_at > now() - make_interval(days => %s) GROUP BY 1, 2 ORDER BY cost DESC",
            (days,),
        ),
    }


@router.get("/v1/admin/settings")
def get_settings(p: Principal = ADMIN):
    return {"settings": db.settings()}


@router.put("/v1/admin/settings")
def put_settings(body: dict, p: Principal = ADMIN):
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            raise HTTPException(400, f"unknown setting {k}")
        if isinstance(DEFAULT_SETTINGS[k], (int, float)) and not isinstance(v, (int, float)):
            raise HTTPException(400, f"{k} must be a number")
        db.set_setting(k, v)
    db.audit(p.key_id, None, "settings.put", body)
    return {"settings": db.settings()}


@router.get("/v1/admin/jobs")
def admin_jobs(limit: int = Query(100, ge=1, le=500), status: str | None = None, p: Principal = ADMIN):
    if status:
        return {
            "jobs": db.q("SELECT * FROM jobs WHERE status = %s ORDER BY id DESC LIMIT %s", (status, min(limit, 500)))
        }
    return {"jobs": db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT %s", (min(limit, 500),))}


@router.post("/v1/admin/jobs/{jid}/retry")
def retry_job(jid: int, p: Principal = ADMIN):
    db.q("UPDATE jobs SET status = 'queued', attempts = 0, run_after = now(), error = NULL WHERE id = %s", (jid,))
    return {"ok": True}


@router.get("/v1/admin/audit")
def admin_audit(limit: int = Query(100, ge=1, le=500), p: Principal = ADMIN):
    return {"audit": db.q("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 500),))}


@router.get("/v1/admin/messages")
def admin_messages(limit: int = Query(100, ge=1, le=500), p: Principal = ADMIN):
    return {
        "messages": db.q(
            "SELECT m.id, m.user_id, u.name, m.direction, m.kind, m.text, m.status, m.meta, m.created_at, m.sent_at FROM messages m LEFT JOIN users u ON u.id = m.user_id ORDER BY m.id DESC LIMIT %s",
            (min(limit, 500),),
        )
    }


class InviteBody(BaseModel):
    email: str | None = None
    role: str = "user"
    days: int = Field(7, ge=1, le=30)


@router.post("/v1/admin/invites")
def create_invite(body: InviteBody, p: Principal = ADMIN):
    tok = secrets.token_urlsafe(24)
    db.q(
        "INSERT INTO invites(email, token_hash, role, expires_at, created_by) VALUES (%s, %s, %s, now() + make_interval(days => %s), %s)",
        (
            body.email,
            hashlib.sha256(tok.encode()).hexdigest(),
            body.role if body.role in ("user", "admin") else "user",
            min(body.days, 30),
            p.user_id,
        ),
    )
    db.audit(p.key_id, None, "invite.create", {"email": body.email})
    return {"token": tok, "note": "shown once"}


@router.get("/v1/admin/invites")
def list_invites(p: Principal = ADMIN):
    return {
        "invites": db.q(
            "SELECT id, email, role, expires_at, used_at, created_at FROM invites ORDER BY created_at DESC LIMIT 100"
        )
    }
