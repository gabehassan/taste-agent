"""Phone login: a six-digit code texted to a registered number, exchanged for a 30-day user key."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import blooio, db, login, ratelimit
from ..auth import USER, Principal

router = APIRouter()


@router.get("/v1/public/config")
def public_config():
    return {"phone": blooio.NUMBER if blooio.enabled() else None, "open_signup": bool(db.setting("open_signup"))}


class AuthRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=40)


@router.post("/v1/auth/request")
def auth_request(body: AuthRequest, request: Request):
    """Keep account existence private; the UI never promises a text was sent."""
    ratelimit.hit(f"auth_ip:{ratelimit.client_ip(request)}", 10, 3600)
    phone = login.phone_number(body.phone)
    ratelimit.hit(f"auth_phone:{phone}", 3, 3600)
    h = db.q("SELECT * FROM handles WHERE address = %s", (phone,), one=True)
    if h:
        u = db.get_user(h["user_id"])
        if u and u["status"] == "active":
            login.issue(u, phone=phone)
    return {"ok": True}


class AuthExchange(BaseModel):
    token: str = Field(min_length=1, max_length=20)
    phone: str = Field(min_length=1, max_length=40)


@router.post("/v1/auth/exchange")
def auth_exchange(body: AuthExchange, request: Request):
    ip = ratelimit.client_ip(request)
    ratelimit.hit(f"auth_x:{ip}", 30, 3600)
    return login.exchange(body.phone, body.token, ip)


@router.post("/v1/auth/logout")
def auth_logout(p: Principal = USER):
    db.q("UPDATE api_keys SET revoked_at = now() WHERE id = %s", (p.key_id,))
    return {"ok": True}
