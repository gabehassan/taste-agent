"""Small, explicit memories and return-to-reading signals. No model calls on page views."""
import datetime as dt
import hashlib
import json

from fastapi import HTTPException

from . import db


def memories(uid):
    return db.q("SELECT id, text, source, evidence, created_at FROM user_memories WHERE user_id = %s ORDER BY created_at DESC LIMIT 30", (uid,))


def remember(uid, text, source="user", evidence=None):
    text = text.strip()
    if not text or len(text) > 500:
        raise HTTPException(422, "keep a memory between 1 and 500 characters")
    with db.transaction():
        db.q("SELECT id FROM users WHERE id = %s FOR NO KEY UPDATE", (uid,))
        existing = db.q("SELECT id FROM user_memories WHERE user_id = %s AND text = %s", (uid, text), one=True)
        if existing:
            return existing
        if len(memories(uid)) >= 30:
            raise HTTPException(409, "memory is full; remove an outdated memory first")
        return db.q("INSERT INTO user_memories(user_id,text,source,evidence) VALUES (%s,%s,%s,%s) RETURNING id",
                    (uid, text, source, (evidence or "")[:500]), one=True)


def context(uid):
    rows = memories(uid)
    # Bounded independently from the archive size. Structured facts remain inspectable.
    return json.dumps([{"id": str(r["id"]), "preference": r["text"]} for r in rows], ensure_ascii=False)


def feedback(uid, item_id, action):
    if action not in {"finished", "later", "not_for_me"}:
        raise HTTPException(422, "unknown feedback")
    with db.transaction():
        it = db.q("SELECT * FROM items WHERE id = %s AND user_id = %s FOR UPDATE", (item_id, uid), one=True)
        if not it:
            raise HTTPException(404, "no such item")
        if action == "finished":
            if it["status"] == "read":
                return {"ok": True}
            db.update_item(item_id, status="read", meta={**it["meta"], "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        elif action == "later":
            until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)).isoformat()
            db.update_item(item_id, meta={**it["meta"], "snoozed_until": until})
        else:
            db.update_item(item_id, status="archived", meta={**it["meta"], "not_for_me": True})
        db.q("INSERT INTO item_events(user_id,item_id,kind) VALUES (%s,%s,%s)", (uid, item_id, action))
        db.count_new_items(uid)
    return {"ok": True}


def eligible(it, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if it["status"] != "unread" or "junk" in (it.get("tags") or []):
        return False
    until = (it.get("meta") or {}).get("snoozed_until")
    if until:
        try:
            if dt.datetime.fromisoformat(until) > now:
                return False
        except (ValueError, TypeError):
            pass
    return True


def daily(uid, date):
    now = dt.datetime.now(dt.timezone.utc)
    items = [i for i in db.list_items(uid, limit=500) if eligible(i, now)]
    def stable(it):
        return hashlib.sha256(f"{uid}:{date}:{it['id']}".encode()).hexdigest()
    items.sort(key=stable)
    chosen = []
    options = [
        ("a small opening", "a few minutes is enough", [i for i in items if 0 < (i.get("read_minutes") or 0) <= 10]),
        ("worth coming back to", "something you saved a little while ago", sorted([i for i in items if (now-i["created_at"]).days >= 5], key=lambda i: i["created_at"])),
        ("follow your curiosity", "one more thread to pull", items),
    ]
    for label, reason, pool in options:
        pick = next((i for i in pool if i["id"] not in {x["item"]["id"] for x in chosen}), None)
        if pick:
            clean = {k: pick.get(k) for k in ("id", "title", "author", "kind", "source", "summary", "why", "url", "read_minutes", "tags", "meta", "created_at")}
            clean["quote"] = (pick.get("snippets") or [""])[0]
            chosen.append({"label": label, "reason": reason, "item": clean})
    completed = db.q("SELECT COUNT(DISTINCT item_id) AS n FROM item_events WHERE user_id=%s AND kind='finished' AND created_at > now()-interval '7 days'", (uid,), one=True)["n"]
    total = db.count_items(uid, "read")
    return {"picks": chosen, "finished_week": completed, "finished_total": total,
            "available": len(items), "memories": memories(uid)}
