"""Decide when to resurface something and what to pick."""
import datetime as dt
import random
import time

from . import db
from .config import (MIN_GAP_MINUTES, OBSERVATION_CHANCE, SURFACES_PER_DAY, WAKE_END, WAKE_START)


def todays_plan(now=None):
    now = now or dt.datetime.now()
    key = f"plan:{now:%Y-%m-%d}"
    plan = db.get_state(key)
    if plan is None:
        plan = _make_plan(now)
        db.set_state(key, plan)
    return key, plan


def _make_plan(now):
    start = now.replace(hour=WAKE_START, minute=0, second=0, microsecond=0)
    end = now.replace(hour=WAKE_END, minute=0, second=0, microsecond=0)
    lo = max(start, now + dt.timedelta(minutes=20))
    if lo >= end:
        return []
    span = (end - lo).total_seconds()
    times = []
    for _ in range(200):
        if len(times) >= SURFACES_PER_DAY:
            break
        t = lo + dt.timedelta(seconds=random.uniform(0, span))
        if all(abs((t - u).total_seconds()) >= MIN_GAP_MINUTES * 60 for u in times):
            times.append(t)
    times.sort()
    return [{"at": t.isoformat(timespec="minutes"), "done": False} for t in times]


def due_slot(now=None):
    """Return (key, index) of a due, unsent slot, or None."""
    now = now or dt.datetime.now()
    if db.get_state("paused", False):
        return None
    key, plan = todays_plan(now)
    last = db.last_surface()
    if last and time.time() - last["created_at"] < MIN_GAP_MINUTES * 60:
        return None
    for i, slot in enumerate(plan):
        if not slot["done"] and dt.datetime.fromisoformat(slot["at"]) <= now:
            return key, i
    return None


def mark_slot_done(key, i):
    plan = db.get_state(key) or []
    if i < len(plan):
        plan[i]["done"] = True
        db.set_state(key, plan)


def pick_item(exclude_id=None):
    items = [i for i in db.list_items(limit=500) if i["status"] != "archived" and i["snippets"]]
    now = time.time()
    last = db.last_surface()
    last_kind = db.get_item(last["item_id"])["kind"] if last and last.get("item_id") else None
    weighted = []
    for it in items:
        if it["id"] == exclude_id:
            continue
        if it["last_surfaced_at"] and now - it["last_surfaced_at"] < 5 * 86400:
            continue
        age_days = (now - it["created_at"]) / 86400
        w = 1.0
        if it["surfaced_count"] == 0:
            w += 0.6
        if age_days < 1:
            w *= 0.5      # still fresh in his head
        elif age_days < 14:
            w *= 1.5      # sweet spot: half forgotten
        if it["status"] == "read":
            w *= 0.6
        if it["kind"] == last_kind:
            w *= 0.7      # vary the kind
        w /= (1 + it["surfaced_count"])
        weighted.append((w, it))
    if not weighted:
        return None
    total = sum(w for w, _ in weighted)
    r = random.uniform(0, total)
    for w, it in weighted:
        r -= w
        if r <= 0:
            return it
    return weighted[-1][1]


def format_surface(item):
    snippets = item["snippets"]
    snippet = snippets[item["surfaced_count"] % len(snippets)]
    by = f" by {item['author']}" if item.get("author") else ""
    src = item.get("source") or item["kind"]
    lines = [f"“{snippet}”", "", f"from: {item['title']}{by} ({src})"]
    if item.get("url"):
        lines.append(item["url"])
    return "\n".join(lines)


def next_surface(force_kind=None):
    """Compose the next thing to send: (kind, item_or_None, text)."""
    profile = db.latest_profile()
    want_obs = force_kind == "observation" or (force_kind is None and profile and profile["observations"]
                                               and random.random() < OBSERVATION_CHANCE)
    if want_obs and profile and profile["observations"]:
        used = set(db.get_state("used_observations", []) or [])
        pool = [o for o in profile["observations"] if o not in used] or profile["observations"]
        obs = random.choice(pool)
        used.add(obs)
        db.set_state("used_observations", list(used)[-100:])
        return "observation", None, obs
    item = pick_item()
    if not item:
        return None, None, None
    return "snippet", item, format_surface(item)
