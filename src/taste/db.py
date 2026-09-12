import json
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  url TEXT,
  kind TEXT,
  source TEXT,
  title TEXT,
  author TEXT,
  raw_text TEXT,
  summary TEXT,
  snippets TEXT DEFAULT '[]',
  tags TEXT DEFAULT '[]',
  why TEXT,
  read_minutes INTEGER DEFAULT 0,
  status TEXT DEFAULT 'unread',
  note TEXT,
  msg_rowid INTEGER,
  surfaced_count INTEGER DEFAULT 0,
  last_surfaced_at REAL,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS items_url ON items(url);
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY,
  text TEXT,
  observations TEXT DEFAULT '[]',
  item_count INTEGER,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS sent (
  id INTEGER PRIMARY KEY,
  text TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS surfaces (
  id INTEGER PRIMARY KEY,
  item_id INTEGER,
  kind TEXT,
  text TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY,
  role TEXT,
  content TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


# ---- state -----------------------------------------------------------------

def get_state(key, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(key, value):
    with conn() as c:
        c.execute(
            "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


# ---- items -----------------------------------------------------------------

def _row_to_item(r):
    d = dict(r)
    d["snippets"] = json.loads(d.get("snippets") or "[]")
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def add_item(**f):
    f.setdefault("created_at", time.time())
    f["snippets"] = json.dumps(f.get("snippets") or [])
    f["tags"] = json.dumps(f.get("tags") or [])
    cols = ",".join(f.keys())
    qs = ",".join("?" * len(f))
    with conn() as c:
        cur = c.execute(f"INSERT INTO items({cols}) VALUES({qs})", tuple(f.values()))
        return cur.lastrowid


def get_item(item_id):
    with conn() as c:
        r = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return _row_to_item(r) if r else None


def find_by_url(url):
    with conn() as c:
        r = c.execute("SELECT * FROM items WHERE url=? ORDER BY id DESC", (url,)).fetchone()
    return _row_to_item(r) if r else None


def update_item(item_id, **f):
    if "snippets" in f:
        f["snippets"] = json.dumps(f["snippets"])
    if "tags" in f:
        f["tags"] = json.dumps(f["tags"])
    sets = ",".join(f"{k}=?" for k in f)
    with conn() as c:
        c.execute(f"UPDATE items SET {sets} WHERE id=?", (*f.values(), item_id))


def list_items(limit=50, status=None, since=None):
    q = "SELECT * FROM items"
    w, p = [], []
    if status:
        w.append("status=?"); p.append(status)
    if since:
        w.append("created_at>=?"); p.append(since)
    if w:
        q += " WHERE " + " AND ".join(w)
    q += " ORDER BY id DESC LIMIT ?"
    p.append(limit)
    with conn() as c:
        return [_row_to_item(r) for r in c.execute(q, p)]


def search_items(query, limit=10):
    like = f"%{query}%"
    with conn() as c:
        rows = c.execute(
            """SELECT * FROM items WHERE title LIKE ? OR summary LIKE ? OR tags LIKE ?
               OR raw_text LIKE ? OR note LIKE ? ORDER BY id DESC LIMIT ?""",
            (like, like, like, like, like, limit),
        )
        return [_row_to_item(r) for r in rows]


def count_items():
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM items").fetchone()[0]


# ---- profile ---------------------------------------------------------------

def save_profile(text, observations, item_count):
    with conn() as c:
        c.execute(
            "INSERT INTO profile(text,observations,item_count,created_at) VALUES(?,?,?,?)",
            (text, json.dumps(observations), item_count, time.time()),
        )


def latest_profile():
    with conn() as c:
        r = c.execute("SELECT * FROM profile ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    d["observations"] = json.loads(d["observations"] or "[]")
    return d


# ---- sent / surfaces / chat ------------------------------------------------

def log_sent(text):
    with conn() as c:
        c.execute("INSERT INTO sent(text,created_at) VALUES(?,?)", (text, time.time()))


def recent_sent_texts(hours=48):
    with conn() as c:
        rows = c.execute("SELECT text FROM sent WHERE created_at>?", (time.time() - hours * 3600,))
        return {r["text"] for r in rows}


def sends_in_last_hour():
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM sent WHERE created_at>?", (time.time() - 3600,)).fetchone()[0]


def log_surface(item_id, kind, text):
    with conn() as c:
        c.execute(
            "INSERT INTO surfaces(item_id,kind,text,created_at) VALUES(?,?,?,?)",
            (item_id, kind, text, time.time()),
        )


def last_surface():
    with conn() as c:
        r = c.execute("SELECT * FROM surfaces ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def add_chat(role, content):
    with conn() as c:
        c.execute("INSERT INTO chat(role,content,created_at) VALUES(?,?,?)", (role, content, time.time()))


def recent_chat(n=12, max_age_hours=12):
    with conn() as c:
        rows = c.execute(
            "SELECT role,content FROM chat WHERE created_at>? ORDER BY id DESC LIMIT ?",
            (time.time() - max_age_hours * 3600, n),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
