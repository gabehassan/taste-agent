"""External taste sources: Letterboxd and Goodreads via their per-user RSS feeds."""
import html
import logging
import re
from urllib.parse import urlparse

import feedparser

from . import db, netguard

log = logging.getLogger("taste.connections")

TYPES = {
    "letterboxd": {"label": "Letterboxd", "config": ["username"], "multi": False},
    "goodreads": {"label": "Goodreads", "config": ["user_id"], "multi": False},
    "substack": {"label": "Substack", "config": ["url"], "multi": True},
    "rss": {"label": "RSS feed", "config": ["url"], "multi": True},
}


def substack_feed(x):
    """'name', 'name.substack.com', 'https://name.substack.com/p/post', or a custom domain -> feed url."""
    x = (x or "").strip().rstrip("/")
    if not x:
        return ""
    if "." not in x and "/" not in x:
        return f"https://{x}.substack.com/feed"
    if not x.startswith("http"):
        x = "https://" + x
    u = urlparse(x)
    return f"{u.scheme}://{u.netloc}/feed"


def sync(connection_id):
    c = db.q("SELECT * FROM connections WHERE id = %s", (connection_id,), one=True)
    if not c or c["status"] != "active":
        return
    try:
        n = {"letterboxd": _letterboxd, "goodreads": _goodreads, "rss": _rss, "substack": _substack}[c["type"]](c)
        db.q("UPDATE connections SET last_synced_at = now(), last_error = NULL WHERE id = %s", (c["id"],))
        log.info("connection %s (%s) synced %s new", c["id"], c["type"], n)
        if n:
            db.count_new_items(c["user_id"], n)
    except Exception as e:
        log.exception("sync failed")
        db.q("UPDATE connections SET last_error = %s WHERE id = %s", (str(e)[:500], c["id"]))


def sync_all_due(hours=1):
    for c in db.q("SELECT id FROM connections WHERE status = 'active' AND (last_synced_at IS NULL OR last_synced_at < now() - make_interval(hours => %s))", (hours,)):
        db.enqueue(None, "sync_connection", {"connection_id": str(c["id"])})


def _feed(url):
    r = netguard.get(url, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
    r.raise_for_status()
    return feedparser.parse(r.content)


def _upsert(user_id, source, external_id, **fields):
    if db.q("SELECT 1 FROM items WHERE user_id = %s AND source = %s AND external_id = %s", (user_id, source, external_id)):
        return 0
    db.add_item(user_id, source=source, external_id=external_id, status="read", **fields)
    return 1


def _letterboxd(c):
    user = c["config"]["username"].strip().lstrip("@")
    feed = _feed(f"https://letterboxd.com/{user}/rss/")
    n = 0
    for e in feed.entries:
        if not e.get("letterboxd_filmtitle"):
            continue
        rating = e.get("letterboxd_memberrating")
        review = re.sub(r"<[^>]+>", "", html.unescape(e.get("summary", ""))).strip()
        review = re.sub(r"^\s*Watched on .*?\.\s*", "", review)
        title = f"{e['letterboxd_filmtitle']} ({e.get('letterboxd_filmyear', '')})".replace(" ()", "")
        snippets = [review[:400]] if len(review) > 20 else []
        n += _upsert(c["user_id"], "letterboxd", e.get("id") or e.get("link"), url=e.get("link"), canonical_url=e.get("link"),
                     kind="film", title=title, summary=(f"rated {rating}/5. " if rating else "") + (review[:300] or "watched."),
                     snippets=snippets, tags=["film"], raw_text=review,
                     meta={"rating": float(rating) if rating else None, "watched": e.get("letterboxd_watcheddate"), "rewatch": e.get("letterboxd_rewatch")})
    return n


def _goodreads(c):
    uid = re.sub(r"\D", "", str(c["config"]["user_id"]))
    n = 0
    for shelf in ("read", "currently-reading", "to-read"):
        feed = _feed(f"https://www.goodreads.com/review/list_rss/{uid}?shelf={shelf}")
        for e in feed.entries:
            rating = e.get("user_rating")
            desc = re.sub(r"<[^>]+>", "", html.unescape(e.get("book_description", "") or "")).strip()
            review = re.sub(r"<[^>]+>", "", html.unescape(e.get("user_review", "") or "")).strip()
            n += _upsert(c["user_id"], "goodreads", e.get("book_id") or e.get("id"), url=e.get("link"), canonical_url=e.get("link"),
                         kind="book", title=e.get("title", ""), author=e.get("author_name", ""),
                         summary=(f"rated {rating}/5. " if rating and rating != "0" else "") + (review[:300] or desc[:300]),
                         snippets=[s for s in (review[:400], desc[:400]) if len(s) > 20][:2], tags=["book", shelf], raw_text=desc,
                         meta={"rating": float(rating) if rating and rating != "0" else None, "shelf": shelf,
                               "thumbnail": e.get("book_large_image_url") or e.get("book_image_url")})
    return n


def _rss(c):
    feed = _feed(c["config"]["url"])
    n = 0
    for e in feed.entries[:30]:
        link = e.get("link")
        if not link:
            continue
        if db.q("SELECT 1 FROM items WHERE user_id = %s AND canonical_url = %s", (c["user_id"], link)):
            continue
        db.enqueue(c["user_id"], "ingest_url", {"url": link, "note": f"from feed {feed.feed.get('title', '')}", "notify": False})
        n += 1
    return n


def _substack(c):
    feed = _feed(substack_feed(c["config"]["url"]))
    title = feed.feed.get("title", "")
    n = 0
    for e in feed.entries[:20]:
        link = e.get("link")
        if not link or db.q("SELECT 1 FROM items WHERE user_id = %s AND canonical_url = %s", (c["user_id"], link)):
            continue
        db.enqueue(c["user_id"], "ingest_url", {"url": link, "note": f"from {title or 'a substack'} you read", "notify": False})
        n += 1
    if title and not c["config"].get("title"):
        db.q("UPDATE connections SET config = config || %s WHERE id = %s", (db.J({"title": title}), c["id"]))
    return n
