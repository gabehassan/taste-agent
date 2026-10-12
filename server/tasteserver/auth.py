import hashlib
import secrets

from fastapi import Depends, HTTPException, Request

from . import db

SCOPES = {"transport", "user", "admin"}


def new_key():
    raw = "tk_" + secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest(), raw[:10]


def create_key(user_id, name, scopes, expires_days=None):
    raw, h, prefix = new_key()
    if expires_days:
        r = db.q(
            "INSERT INTO api_keys(user_id, name, key_hash, prefix, scopes, expires_at) VALUES (%s, %s, %s, %s, %s, now() + make_interval(days => %s)) RETURNING id",
            (user_id, name, h, prefix, list(scopes), int(expires_days)),
            one=True,
        )
    else:
        r = db.q(
            "INSERT INTO api_keys(user_id, name, key_hash, prefix, scopes) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, name, h, prefix, list(scopes)),
            one=True,
        )
    return raw, r["id"]


def lookup(raw):
    if not raw or not raw.startswith("tk_"):
        return None
    h = hashlib.sha256(raw.encode()).hexdigest()
    k = db.q(
        "SELECT * FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())",
        (h,),
        one=True,
    )
    if not k:
        return None
    db.q("UPDATE api_keys SET last_used_at = now() WHERE id = %s", (k["id"],))
    return k


class Principal:
    def __init__(self, key, user):
        self.key = key
        self.user = user
        self.scopes = set(key["scopes"])
        self.key_id = key["id"]

    @property
    def user_id(self):
        return self.user["id"] if self.user else None

    def is_admin(self):
        return "admin" in self.scopes


def principal(request: Request) -> Principal:
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    raw = raw.strip() if scheme.lower() == "bearer" else ""
    k = lookup(raw)
    if not k:
        raise HTTPException(401, "invalid or missing api key")
    user = db.get_user(k["user_id"]) if k["user_id"] else None
    if user and user["status"] != "active":
        raise HTTPException(403, "user disabled")
    request.state.principal = Principal(k, user)
    return request.state.principal


def require(*scopes):
    def dep(p: Principal = Depends(principal)):
        if p.is_admin() or p.scopes & set(scopes):
            return p
        raise HTTPException(403, f"needs scope: {' or '.join(scopes)}")

    return dep


def target_user(request: Request, p: Principal):
    """The user a request acts on. Admins may pass ?user_id= to act for someone."""
    uid = request.query_params.get("user_id")
    if uid and p.is_admin():
        u = db.get_user(uid)
        if not u:
            raise HTTPException(404, "no such user")
        return u
    if not p.user:
        raise HTTPException(400, "admin key has no user; pass ?user_id=")
    return p.user


# Route dependencies. An admin key satisfies every scope.
TRANSPORT = Depends(require("transport"))
USER = Depends(require("user"))
ADMIN = Depends(require("admin"))
