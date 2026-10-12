"""Per-user resurfacing: when, and what."""

import datetime as dt
import random
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db, memory
from .config import DEFAULT_TZ


def _now(user):
    try:
        return dt.datetime.now(ZoneInfo(user.get("tz") or DEFAULT_TZ))
    except (ValueError, ZoneInfoNotFoundError):
        return dt.datetime.now(ZoneInfo(DEFAULT_TZ))


def todays_plan(user):
    now = _now(user)
    state = db.user_state(user["id"])
    plan = state.get("plan") or {}
    if plan.get("date") != now.strftime("%Y-%m-%d"):
        plan = {"date": now.strftime("%Y-%m-%d"), "slots": _make_slots(user, now)}
        db.set_user_state(user["id"], plan=plan)
    return plan


def _make_slots(user, now):
    per_day = int(db.user_setting(user, "surfaces_per_day"))
    ws, we = int(db.user_setting(user, "wake_start")), int(db.user_setting(user, "wake_end"))
    gap = int(db.user_setting(user, "min_gap_minutes")) * 60
    start = now.replace(hour=ws, minute=0, second=0, microsecond=0)
    end = now.replace(hour=we % 24, minute=0, second=0, microsecond=0) + dt.timedelta(days=1 if we == 24 else 0)
    lo = max(start, now + dt.timedelta(minutes=20))
    if lo >= end:
        return []
    span = (end - lo).total_seconds()
    times = []
    for _ in range(300):
        if len(times) >= per_day:
            break
        t = lo + dt.timedelta(seconds=random.uniform(0, span))
        if all(abs((t - u).total_seconds()) >= gap for u in times):
            times.append(t)
    times.sort()
    return [{"at": t.isoformat(timespec="minutes"), "done": False} for t in times]


def due_slot(user):
    if (user.get("settings") or {}).get("paused"):
        return None
    now = _now(user)
    ws, we = int(db.user_setting(user, "wake_start")), int(db.user_setting(user, "wake_end"))
    if not ws <= now.hour < we or int(db.user_setting(user, "surfaces_per_day")) <= 0:
        return None
    # After two unanswered suggestions, leave room for a reply or a website action.
    if not attention_available(user):
        return None
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sent = db.q(
        "SELECT COUNT(*) AS n FROM messages WHERE user_id=%s AND direction='out' AND meta->>'proactive'='true' AND status IN ('queued','sending','sent') AND created_at >= %s",
        (user["id"], start),
        one=True,
    )["n"]
    if sent >= int(db.user_setting(user, "surfaces_per_day")):
        return None
    plan = todays_plan(user)
    last = db.last_surface(user["id"])
    if (
        last
        and (dt.datetime.now(dt.UTC) - last["created_at"]).total_seconds()
        < int(db.user_setting(user, "min_gap_minutes")) * 60
    ):
        return None
    # don't interrupt an active conversation: quiet if they texted in the last 20 min
    recent = db.q(
        "SELECT 1 FROM messages WHERE user_id = %s AND direction = 'in' AND created_at > now() - interval '20 minutes' LIMIT 1",
        (user["id"],),
    )
    if recent:
        return None
    for i, slot in enumerate(plan["slots"]):
        if not slot["done"] and dt.datetime.fromisoformat(slot["at"]) <= now:
            return i
    return None


def mark_slot_done(user, i):
    plan = db.user_state(user["id"]).get("plan") or {}
    if i < len(plan.get("slots", [])):
        plan["slots"][i]["done"] = True
        db.set_user_state(user["id"], plan=plan)


def pick_item(user, exclude_id=None):
    items = [i for i in db.list_items(user["id"], limit=500) if memory.eligible(i) and i["snippets"]]
    now = dt.datetime.now(dt.UTC)
    last = db.last_surface(user["id"])
    last_kind = None
    if last and last.get("item_id"):
        li = db.get_item(user["id"], last["item_id"])
        last_kind = li["kind"] if li else None
    weighted = []
    for it in items:
        if it["id"] == exclude_id:
            continue
        if it["last_surfaced_at"] and (now - it["last_surfaced_at"]).total_seconds() < 5 * 86400:
            continue
        age_days = (now - it["created_at"]).total_seconds() / 86400
        w = 1.0
        if it["surfaced_count"] == 0:
            w += 0.6
        if age_days < 1:
            w *= 0.5
        elif age_days < 14:
            w *= 1.5
        if it["status"] == "read":
            w *= 0.6
        if it["kind"] == last_kind:
            w *= 0.7
        reactions = (it.get("meta") or {}).get("reactions") or []
        if "love" in reactions:
            w *= 1.6
        if "dislike" in reactions:
            w *= 0.2
        w /= 1 + it["surfaced_count"]
        weighted.append((w, it))
    if not weighted:
        return None
    r = random.uniform(0, sum(w for w, _ in weighted))
    for w, it in weighted:
        r -= w
        if r <= 0:
            return it
    return weighted[-1][1]


def format_surface(item):
    snippets = item["snippets"]
    snippet = snippets[item["surfaced_count"] % len(snippets)].strip().strip("“”\"'‘’")
    from .prompts import surface_format

    by = f" by {item['author']}" if item.get("author") else ""
    src = item.get("source") or item["kind"]
    return (
        surface_format()
        .format(snippet=snippet, title=item["title"], by=by, source=src, url=item.get("url") or "")
        .rstrip()
    )


def next_surface(user, force_kind=None):
    profile = db.latest_profile(user["id"])
    chance = float(db.user_setting(user, "observation_chance"))
    want_obs = force_kind == "observation" or (
        force_kind is None and profile and profile["observations"] and random.random() < chance
    )
    if want_obs and profile and profile["observations"]:
        state = db.user_state(user["id"])
        used = set(state.get("used_observations") or [])
        pool = [o for o in profile["observations"] if o not in used]
        if pool:
            obs = random.choice(pool)
            used.add(obs)
            db.set_user_state(user["id"], used_observations=list(used)[-100:])
            return "observation", None, obs
    item = pick_item(user)
    if not item:
        return None, None, None
    return "snippet", item, format_surface(item)


def attention_available(user):
    """Inactivity reduces contact; it is never treated as evidence of dislike."""
    uid = user["id"]
    row = db.q(
        """SELECT COUNT(*) AS n FROM messages WHERE user_id=%s AND direction='out'
        AND meta->>'proactive'='true' AND status IN ('queued','sending','sent')
        AND created_at > GREATEST(
            COALESCE((SELECT max(created_at) FROM messages WHERE user_id=%s AND direction='in'), '-infinity'::timestamptz),
            COALESCE((SELECT max(created_at) FROM item_events WHERE user_id=%s), '-infinity'::timestamptz))""",
        (uid, uid, uid),
        one=True,
    )
    return row["n"] < 2


def proactive_candidates(user):
    now = dt.datetime.now(dt.UTC)
    items = [
        i
        for i in db.list_items(user["id"], limit=500)
        if memory.eligible(i, now)
        and i.get("snippets")
        and (not i.get("last_surfaced_at") or (now - i["last_surfaced_at"]).days >= 5)
    ]
    recent = db.recent_chat(user["id"], n=6, max_age_hours=72)
    interest = memory.context(user["id"]) + " " + " ".join(c["content"] for c in recent if c["role"] == "user")
    words = set(re.findall(r"[a-z]{4,}", interest.lower()))

    def score(it):
        terms = set(re.findall(r"[a-z]{4,}", " ".join([it["title"] or "", *(it.get("tags") or [])]).lower()))
        return (len(words & terms), not bool(it["surfaced_count"]), (now - it["created_at"]).days)

    return sorted(items, key=score, reverse=True)[:8]
