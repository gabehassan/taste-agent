"""Routes for a signed-in user. Admin keys may act for any user with ?user_id=."""

import contextlib
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import brain, db, memory, ratelimit, storage
from ..auth import USER, Principal, target_user
from ..connections import TYPES as CONNECTION_TYPES
from ..connections import substack_feed
from ..netguard import check_url
from ..prompts import P
from ..scheduler import _now, todays_plan
from .common import check_tz, clean_row

router = APIRouter()


@router.get("/v1/me")
def me(request: Request, p: Principal = USER):
    u = target_user(request, p)
    uid = u["id"]
    streak = db.q(
        """WITH d AS (SELECT DISTINCT (created_at AT TIME ZONE %s)::date AS day FROM messages WHERE user_id = %s AND direction = 'in')
                     SELECT COUNT(*) AS n FROM (SELECT day, (CURRENT_DATE - day) - ROW_NUMBER() OVER (ORDER BY day DESC) AS g FROM d) x
                     WHERE g IN (-1, 0) AND day >= CURRENT_DATE - 60""",
        (u.get("tz") or "UTC", uid),
        one=True,
    )["n"]
    unread_minutes = db.q(
        "SELECT COALESCE(SUM(read_minutes), 0) AS m FROM items WHERE user_id = %s AND status = 'unread'",
        (uid,),
        one=True,
    )["m"]
    forgotten = db.q(
        """SELECT id, title, kind, url, created_at, meta FROM items WHERE user_id = %s AND status = 'unread' AND surfaced_count = 0
                        AND created_at < now() - interval '5 days' ORDER BY created_at ASC LIMIT 1""",
        (uid,),
        one=True,
    )
    first = db.q("SELECT MIN(created_at) AS t FROM items WHERE user_id = %s", (uid,), one=True)["t"]
    return {
        "user": clean_row(u),
        "scopes": sorted(p.scopes),
        "spend_today": db.spend(uid, 1),
        "plan": todays_plan(u),
        "counts": {
            "items": db.count_items(uid),
            "unread": db.count_items(uid, "unread"),
            "read": db.count_items(uid, "read"),
        },
        "one_liner": (db.latest_profile(uid) or {}).get("one_liner"),
        "streak_days": int(streak or 0),
        "unread_minutes": int(unread_minutes or 0),
        "forgotten": clean_row(forgotten) if forgotten else None,
        "since": first,
    }


class MeSettings(BaseModel):
    name: str | None = None
    tz: str | None = None
    surfaces_per_day: int | None = None
    wake_start: int | None = None
    wake_end: int | None = None
    paused: bool | None = None


@router.patch("/v1/me")
def patch_me(body: MeSettings, request: Request, p: Principal = USER):
    u = target_user(request, p)
    if body.name is not None:
        db.q("UPDATE users SET name = %s WHERE id = %s", (body.name[:80], u["id"]))
    if body.tz is not None:
        check_tz(body.tz)
        db.q("UPDATE users SET tz = %s WHERE id = %s", (body.tz, u["id"]))
    patch = {}
    if body.surfaces_per_day is not None:
        patch["surfaces_per_day"] = max(0, min(body.surfaces_per_day, 8))
    if body.wake_start is not None:
        patch["wake_start"] = max(0, min(body.wake_start, 23))
    if body.wake_end is not None:
        patch["wake_end"] = max(1, min(body.wake_end, 24))
    if body.paused is not None:
        patch["paused"] = body.paused
    if patch:
        db.q("UPDATE users SET settings = settings || %s, state = state - 'plan' WHERE id = %s", (db.J(patch), u["id"]))
    return clean_row(db.get_user(u["id"]))


@router.get("/v1/items")
def items(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    p: Principal = USER,
):
    u = target_user(request, p)
    limit = min(limit, 200)
    rows = db.search_items(u["id"], q, limit) if q else db.list_items(u["id"], limit, status, offset, kind)
    return {"items": [clean_row(r) for r in rows], "total": db.count_items(u["id"])}


@router.get("/v1/items/{item_id}")
def item(item_id: int, request: Request, p: Principal = USER):
    u = target_user(request, p)
    it = db.get_item(u["id"], item_id)
    if not it:
        raise HTTPException(404)
    d = clean_row(it)
    d["media_urls"] = [storage.presign(m["key"]) for m in (it.get("media") or []) if m.get("key")]
    return d


class ItemPatch(BaseModel):
    status: str | None = None
    note: str | None = Field(None, max_length=2000)
    tags: list[str] | None = Field(None, max_length=20)


@router.patch("/v1/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, request: Request, p: Principal = USER):
    u = target_user(request, p)
    if not db.get_item(u["id"], item_id):
        raise HTTPException(404)
    f = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in f and f["status"] not in ("unread", "read", "archived"):
        raise HTTPException(400, "bad status")
    if f.get("status") == "read":
        memory.feedback(u["id"], item_id, "finished")
        f.pop("status")
    if f:
        db.update_item(item_id, **f)
    return clean_row(db.get_item(u["id"], item_id))


@router.delete("/v1/items/{item_id}")
def delete_item(item_id: int, request: Request, p: Principal = USER):
    u = target_user(request, p)
    it = db.get_item(u["id"], item_id)
    if not it:
        raise HTTPException(404)
    for m in it.get("media") or []:
        with contextlib.suppress(Exception):
            storage.delete(m["key"])
    db.q("DELETE FROM items WHERE id = %s", (item_id,))
    return {"ok": True}


class IngestBody(BaseModel):
    url: str = Field(max_length=2048)
    note: str = Field("", max_length=2000)
    notify: bool = False


@router.post("/v1/items/ingest")
def ingest(body: IngestBody, request: Request, p: Principal = USER):
    u = target_user(request, p)
    ok, why = db.spend_ok(u)
    if not ok:
        raise HTTPException(402, f"spend cap: {why}")
    ratelimit.hit(f"ingest:{u['id']}", int(db.setting("rate_ingest_per_day")), 86400)
    job = db.enqueue(u["id"], "ingest_url", {"url": body.url, "note": body.note, "notify": body.notify})
    return {"job_id": job}


@router.get("/v1/profile")
def profile(request: Request, p: Principal = USER):
    u = target_user(request, p)
    return {
        "profile": clean_row(db.latest_profile(u["id"])),
        "history": [
            {"id": r["id"], "created_at": r["created_at"], "item_count": r["item_count"]}
            for r in db.q(
                "SELECT id, created_at, item_count FROM profiles WHERE user_id = %s ORDER BY id DESC LIMIT 20",
                (u["id"],),
            )
        ],
    }


@router.post("/v1/profile/refresh")
def profile_refresh(request: Request, p: Principal = USER):
    u = target_user(request, p)
    ok, why = db.spend_ok(u)
    if not ok:
        raise HTTPException(402, f"spend cap: {why}")
    return {"job_id": db.enqueue(u["id"], "refresh_profile")}


@router.post("/v1/surface")
def surface_now(request: Request, kind: str | None = None, p: Principal = USER):
    u = target_user(request, p)
    return {"job_id": db.enqueue(u["id"], "surface", {"kind": kind})}


@router.get("/v1/surfaces")
def surfaces(request: Request, limit: int = Query(50, ge=1, le=200), p: Principal = USER):
    u = target_user(request, p)
    return {
        "surfaces": db.q(
            "SELECT * FROM surfaces WHERE user_id = %s ORDER BY id DESC LIMIT %s", (u["id"], min(limit, 200))
        )
    }


@router.get("/v1/messages")
def messages(request: Request, limit: int = Query(50, ge=1, le=200), p: Principal = USER):
    u = target_user(request, p)
    return {
        "messages": db.q(
            "SELECT id, direction, kind, text, status, attachments, meta, created_at, sent_at FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (u["id"], min(limit, 200)),
        )
    }


# ---- connections ---------------------------------------------------------------


@router.get("/v1/connections")
def connections(request: Request, p: Principal = USER):
    u = target_user(request, p)
    return {
        "connections": db.q("SELECT * FROM connections WHERE user_id = %s ORDER BY created_at", (u["id"],)),
        "types": CONNECTION_TYPES,
    }


class ConnectionBody(BaseModel):
    type: str
    config: dict


@router.post("/v1/connections")
def add_connection(body: ConnectionBody, request: Request, p: Principal = USER):
    u = target_user(request, p)
    if body.type not in CONNECTION_TYPES:
        raise HTTPException(400, "unknown connection type")
    need = CONNECTION_TYPES[body.type]["config"]
    cfg = {k: str(body.config.get(k, "")).strip()[:300] for k in need}
    if any(not v for v in cfg.values()):
        raise HTTPException(400, f"config needs: {', '.join(need)}")
    if body.type == "substack":
        cfg["url"] = substack_feed(cfg["url"])
    if body.type in ("rss", "substack"):
        check_url(cfg["url"])
    if not CONNECTION_TYPES[body.type].get("multi") and db.q(
        "SELECT 1 FROM connections WHERE user_id = %s AND type = %s", (u["id"], body.type)
    ):
        raise HTTPException(400, "already connected")
    if db.q(
        "SELECT 1 FROM connections WHERE user_id = %s AND type = %s AND config->>'url' = %s",
        (u["id"], body.type, cfg.get("url")),
    ):
        raise HTTPException(400, "already added")
    if len(db.q("SELECT 1 FROM connections WHERE user_id = %s", (u["id"],))) >= 25:
        raise HTTPException(400, "too many connections")
    r = db.q(
        "INSERT INTO connections(user_id, type, config) VALUES (%s, %s, %s) RETURNING *",
        (u["id"], body.type, db.J(cfg)),
        one=True,
    )
    db.enqueue(u["id"], "sync_connection", {"connection_id": str(r["id"])})
    db.audit(p.key_id, u["id"], "connection.add", {"type": body.type})
    return dict(r)


@router.post("/v1/connections/{cid}/sync")
def sync_connection(cid: str, request: Request, p: Principal = USER):
    u = target_user(request, p)
    if not db.q("SELECT 1 FROM connections WHERE id = %s AND user_id = %s", (cid, u["id"])):
        raise HTTPException(404)
    ratelimit.hit(f"sync:{cid}", 6, 3600)
    return {"job_id": db.enqueue(u["id"], "sync_connection", {"connection_id": cid})}


@router.delete("/v1/connections/{cid}")
def delete_connection(cid: str, request: Request, p: Principal = USER):
    u = target_user(request, p)
    db.q("DELETE FROM connections WHERE id = %s AND user_id = %s", (cid, u["id"]))
    db.audit(p.key_id, u["id"], "connection.delete", {"id": cid})
    return {"ok": True}


@router.get("/v1/me/today")
def today(request: Request, p: Principal = USER):
    u = target_user(request, p)
    return memory.daily(u["id"], _now(u).date().isoformat())


class MemoryBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/v1/me/memories")
def add_memory(body: MemoryBody, request: Request, p: Principal = USER):
    return memory.remember(target_user(request, p)["id"], body.text)


@router.delete("/v1/me/memories/{memory_id}")
def forget_memory(memory_id: uuid.UUID, request: Request, p: Principal = USER):
    uid = target_user(request, p)["id"]
    db.q("DELETE FROM user_memories WHERE id=%s AND user_id=%s", (memory_id, uid))
    return {"ok": True}


class FeedbackBody(BaseModel):
    action: str


@router.post("/v1/items/{item_id}/feedback")
def item_feedback(item_id: int, body: FeedbackBody, request: Request, p: Principal = USER):
    return memory.feedback(target_user(request, p)["id"], item_id, body.action)


@router.get("/v1/me/memory")
def me_memory(request: Request, p: Principal = USER):
    """Everything that shapes how the agent talks to this user: the learned voice, the taste profile,
    recent conversation memory, what it has texted, reactions, schedule state, and the rendered prompts."""
    u = target_user(request, p)
    state = u.get("state") or {}
    profile = db.latest_profile(u["id"])
    voice_stats = state.get("voice") or {}
    reactions = db.q(
        """SELECT meta->'reactions' AS r, id, title FROM items WHERE user_id = %s AND meta ? 'reactions' ORDER BY id DESC LIMIT 20""",
        (u["id"],),
    )
    tags = db.q(
        """SELECT t AS tag, COUNT(*) AS n FROM items, unnest(tags) AS t WHERE user_id = %s GROUP BY t ORDER BY n DESC, t LIMIT 30""",
        (u["id"],),
    )
    return {
        "user": clean_row(u),
        "voice": {"stats": voice_stats, "sentence": brain.voice_desc(u), "rendered": brain.voice(u)},
        "profile": clean_row(profile),
        "preferences": memory.memories(u["id"]),
        "profile_history": db.q(
            "SELECT id, created_at, item_count, one_liner FROM profiles WHERE user_id = %s ORDER BY id DESC LIMIT 10",
            (u["id"],),
        ),
        "chat_memory": db.recent_chat(u["id"], n=30, max_age_hours=72),
        "recent_texts": db.q(
            "SELECT id, direction, kind, text, status, meta, created_at FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT 30",
            (u["id"],),
        ),
        "surfaces": db.q("SELECT * FROM surfaces WHERE user_id = %s ORDER BY id DESC LIMIT 15", (u["id"],)),
        "reactions": [{"item_id": r["id"], "title": r["title"], "reactions": r["r"] or []} for r in reactions],
        "tags": tags,
        "schedule": {
            "plan": state.get("plan"),
            "settings": u.get("settings"),
            "items_since_profile": state.get("items_since_profile", 0),
            "used_observations": len(state.get("used_observations") or []),
            "cap_notified": state.get("cap_notified"),
        },
        "spend": {"today": db.spend(u["id"], 1), "month": db.spend(u["id"], 30)},
        "prompts": {
            "digest": brain.voice(u) + brain.DIGEST_SYSTEM,
            "chat": brain.voice(u) + brain.CHAT_SYSTEM,
            "profile": brain.voice(u) + brain.PROFILE_SYSTEM,
            "about": {k: P[k]["about"].strip() for k in ("voice", "digest", "chat", "profile")},
        },
    }


LEVELS = [(0, "stranger"), (5, "acquaintance"), (15, "friend"), (40, "close friend"), (100, "knows you")]


def progress_for(u):
    uid = u["id"]
    n_items = db.count_items(uid)
    kinds = db.q("SELECT COUNT(DISTINCT kind) AS n FROM items WHERE user_id = %s", (uid,), one=True)["n"]
    notes = db.q(
        "SELECT COUNT(*) AS n FROM items WHERE user_id = %s AND note IS NOT NULL AND note <> ''", (uid,), one=True
    )["n"]
    reacts = db.q("SELECT COUNT(*) AS n FROM items WHERE user_id = %s AND meta ? 'reactions'", (uid,), one=True)["n"]
    conns = db.q("SELECT type FROM connections WHERE user_id = %s AND status = 'active'", (uid,))
    conn_types = {c["type"] for c in conns}
    chats = db.q("SELECT COUNT(*) AS n FROM chat_turns WHERE user_id = %s AND role = 'user'", (uid,), one=True)["n"]
    read = db.count_items(uid, "read")
    profiles = db.q("SELECT COUNT(*) AS n FROM profiles WHERE user_id = %s", (uid,), one=True)["n"]
    days = db.q(
        "SELECT COUNT(DISTINCT date_trunc('day', created_at)) AS n FROM messages WHERE user_id = %s AND direction = 'in'",
        (uid,),
        one=True,
    )["n"]
    quests = [
        {
            "id": "first_five",
            "label": "send five things",
            "done": n_items >= 5,
            "progress": min(n_items, 5),
            "of": 5,
            "unlocks": "your first taste profile",
        },
        {
            "id": "mix",
            "label": "send three different kinds (an essay, a video, a tweet...)",
            "done": kinds >= 3,
            "progress": min(kinds, 3),
            "of": 3,
            "unlocks": "it stops guessing from one medium",
        },
        {
            "id": "note",
            "label": 'add a note to something you send ("for the argument in part 2")',
            "done": notes >= 1,
            "progress": min(notes, 1),
            "of": 1,
            "unlocks": "why-you-saved-it gets real",
        },
        {
            "id": "react",
            "label": "tapback one of its texts",
            "done": reacts >= 1,
            "progress": min(reacts, 1),
            "of": 1,
            "unlocks": "it learns what lands",
        },
        {
            "id": "talk",
            "label": "ask it what to read tonight",
            "done": chats >= 1,
            "progress": min(chats, 1),
            "of": 1,
            "unlocks": "recommendations from your own pile",
        },
        {
            "id": "read",
            "label": "text 'read' after finishing something it sent",
            "done": read >= 1,
            "progress": min(read, 1),
            "of": 1,
            "unlocks": "it stops resurfacing things you've finished",
        },
        {
            "id": "source",
            "label": "connect letterboxd, goodreads, or a substack",
            "done": len(conn_types) >= 1,
            "progress": min(len(conn_types), 1),
            "of": 1,
            "unlocks": "ratings: the only honest negative signal",
        },
        {
            "id": "fifteen",
            "label": "fifteen things saved",
            "done": n_items >= 15,
            "progress": min(n_items, 15),
            "of": 15,
            "unlocks": "observations start showing up as random texts",
        },
        {
            "id": "week",
            "label": "text it on five different days",
            "done": days >= 5,
            "progress": min(days, 5),
            "of": 5,
            "unlocks": "it can tell habits from moods",
        },
        {
            "id": "forty",
            "label": "forty things saved",
            "done": n_items >= 40,
            "progress": min(n_items, 40),
            "of": 40,
            "unlocks": "it starts connecting things you haven't",
        },
    ]
    points = n_items + 3 * len(conn_types) + 2 * reacts + notes + min(chats, 20) + read + days * 2
    level_i = max(i for i, (th, _) in enumerate(LEVELS) if n_items >= th)
    nxt = LEVELS[level_i + 1] if level_i + 1 < len(LEVELS) else None
    return {
        "level": level_i + 1,
        "title": LEVELS[level_i][1],
        "next": {"title": nxt[1], "at": nxt[0], "items": n_items} if nxt else None,
        "points": points,
        "items": n_items,
        "profiles": profiles,
        "quests": quests,
        "done": sum(q["done"] for q in quests),
        "total": len(quests),
    }


@router.get("/v1/me/progress")
def me_progress(request: Request, p: Principal = USER):
    return progress_for(target_user(request, p))
