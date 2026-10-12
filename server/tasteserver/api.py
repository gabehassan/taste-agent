"""The API process: middleware, startup, and the route modules under routes/."""

import hashlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, ratelimit
from .config import DASHBOARD_ORIGIN, MAX_BODY_BYTES
from .routes import admin, auth, me, relay, webhooks

log = logging.getLogger("taste.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def bootstrap():
    """First boot: create the admin key from ADMIN_BOOTSTRAP_KEY if no keys exist yet."""
    raw = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
    if not raw:
        return
    if not raw.startswith("tk_") or len(raw) < 40:
        log.warning("ADMIN_BOOTSTRAP_KEY ignored: it must start with tk_ and be at least 40 characters")
        return
    if db.q("SELECT 1 FROM api_keys LIMIT 1"):
        return
    h = hashlib.sha256(raw.encode()).hexdigest()
    db.q(
        "INSERT INTO api_keys(user_id, name, key_hash, prefix, scopes) VALUES (NULL, 'bootstrap admin', %s, %s, %s)",
        (h, raw[:10], ["admin"]),
    )
    log.info("bootstrap admin key created")


@asynccontextmanager
async def lifespan(app):
    db.migrate()
    bootstrap()
    yield


class BodyLimit:
    """Caps request bodies as they stream in. Checking Content-Length alone misses chunked uploads.
    Bodies are buffered up to the limit and replayed to the app, so an oversized one never reaches a route."""

    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        too_large = JSONResponse({"detail": "body too large"}, 413)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.limit):
            return await too_large(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > self.limit:
                return await too_large(scope, receive, send)
            if not message.get("more_body"):
                break
        buffered = iter(messages)

        async def replay():
            return next(buffered, None) or await receive()

        await self.app(scope, replay, send)


app = FastAPI(title="taste api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
if DASHBOARD_ORIGIN:
    app.add_middleware(CORSMiddleware, allow_origins=[DASHBOARD_ORIGIN], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path != "/health":
        try:
            ratelimit.hit(f"ip:{ratelimit.client_ip(request)}", int(db.setting("rate_ip_per_min")), 60)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, 429, headers=e.headers)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


app.add_middleware(BodyLimit, limit=MAX_BODY_BYTES)


@app.get("/health")
def health():
    return {"ok": True}


for module in (relay, webhooks, auth, me, admin):
    app.include_router(module.router)
