import pathlib
import time
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL, DEFAULT_SETTINGS

pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=8, open=False,
                      kwargs={"row_factory": dict_row})
_transaction = ContextVar("taste_transaction", default=None)


def open_pool():
    if pool.closed:
        pool.open()


@contextmanager
def conn():
    active = _transaction.get()
    if active is not None:
        yield active
        return
    open_pool()
    with pool.connection() as c:
        yield c


@contextmanager
def transaction():
    """Make related q() calls commit together, including calls in helper modules."""
    with conn() as c:
        with c.transaction():
            token = _transaction.set(c)
            try:
                yield c
            finally:
                _transaction.reset(token)


def q(sql, params=None, one=False):
    with conn() as c:
        cur = c.execute(sql, params)
        if cur.description is None:
            return None
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def J(obj):
    return Jsonb(obj)


def migrate():
    sql = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    with conn() as c:
        c.execute(sql)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT INTO settings(key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", (k, Jsonb(v)))


# ---- settings ---------------------------------------------------------------

_settings_cache = {"at": 0, "data": {}}


def settings():
    if time.time() - _settings_cache["at"] > 30:
        rows = q("SELECT key, value FROM settings")
        _settings_cache["data"] = {r["key"]: r["value"] for r in rows}
        _settings_cache["at"] = time.time()
    return _settings_cache["data"]


def setting(key):
    return settings().get(key, DEFAULT_SETTINGS.get(key))


def set_setting(key, value):
    q("INSERT INTO settings(key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, Jsonb(value)))
    _settings_cache["at"] = 0


# ---- users ------------------------------------------------------------------

def get_user(user_id):
    return q("SELECT * FROM users WHERE id = %s", (user_id,), one=True)


def user_setting(user, key):
    v = (user.get("settings") or {}).get(key)
    if v is None:
        v = setting("default_user_daily_cap_usd") if key == "daily_spend_cap_usd" else setting(key)
    return v


def user_state(user_id):
    r = q("SELECT state FROM users WHERE id = %s", (user_id,), one=True)
    return (r or {}).get("state") or {}


def set_user_state(user_id, **patch):
    q("UPDATE users SET state = COALESCE(state, '{}'::jsonb) || %s WHERE id = %s", (Jsonb(patch), user_id))


# ---- items ------------------------------------------------------------------

def add_item(user_id, **f):
    f["user_id"] = user_id
    for k in ("snippets", "media", "meta"):
        if k in f:
            f[k] = Jsonb(f[k])
    cols = ", ".join(f.keys())
    ph = ", ".join(["%s"] * len(f))
    r = q(f"INSERT INTO items({cols}) VALUES ({ph}) RETURNING id", tuple(f.values()), one=True)
    return r["id"]


def update_item(item_id, **f):
    for k in ("snippets", "media", "meta"):
        if k in f:
            f[k] = Jsonb(f[k])
    sets = ", ".join(f"{k} = %s" for k in f)
    q(f"UPDATE items SET {sets} WHERE id = %s", (*f.values(), item_id))


def get_item(user_id, item_id):
    return q("SELECT * FROM items WHERE id = %s AND user_id = %s", (item_id, user_id), one=True)


def find_by_url(user_id, url):
    return q("SELECT * FROM items WHERE user_id = %s AND (url = %s OR canonical_url = %s) ORDER BY id DESC LIMIT 1",
             (user_id, url, url), one=True)


def list_items(user_id, limit=50, status=None, offset=0, kind=None):
    w = ["user_id = %s"]; p = [user_id]
    if status:
        w.append("status = %s"); p.append(status)
    if kind:
        w.append("kind = %s"); p.append(kind)
    p += [limit, offset]
    return q(f"SELECT * FROM items WHERE {' AND '.join(w)} ORDER BY id DESC LIMIT %s OFFSET %s", p)


def search_items(user_id, query, limit=10):
    return q("""SELECT *, ts_rank(tsv, websearch_to_tsquery('english', %s)) AS rank FROM items
                WHERE user_id = %s AND tsv @@ websearch_to_tsquery('english', %s)
                ORDER BY rank DESC, id DESC LIMIT %s""", (query, user_id, query, limit))


def count_items(user_id, status=None):
    if status:
        return q("SELECT COUNT(*) AS n FROM items WHERE user_id = %s AND status = %s", (user_id, status), one=True)["n"]
    return q("SELECT COUNT(*) AS n FROM items WHERE user_id = %s", (user_id,), one=True)["n"]


# ---- profile / surfaces / chat ------------------------------------------------

def save_profile(user_id, text, observations, one_liner, item_count):
    q("INSERT INTO profiles(user_id, text, observations, one_liner, item_count) VALUES (%s, %s, %s, %s, %s)",
      (user_id, text, Jsonb(observations), one_liner, item_count))


def latest_profile(user_id):
    return q("SELECT * FROM profiles WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,), one=True)


def log_surface(user_id, item_id, kind, text):
    q("INSERT INTO surfaces(user_id, item_id, kind, text) VALUES (%s, %s, %s, %s)", (user_id, item_id, kind, text))


def last_surface(user_id):
    return q("SELECT * FROM surfaces WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,), one=True)


def add_chat(user_id, role, content):
    q("INSERT INTO chat_turns(user_id, role, content) VALUES (%s, %s, %s)", (user_id, role, content))


def recent_chat(user_id, n=12, max_age_hours=12):
    rows = q("""SELECT role, content FROM chat_turns WHERE user_id = %s AND created_at > now() - make_interval(hours => %s)
                ORDER BY id DESC LIMIT %s""", (user_id, max_age_hours, n))
    return list(reversed(rows))


# ---- messages (in/out) ---------------------------------------------------------

def queue_outbound(user_id, text, handle_id=None, meta=None):
    return q("INSERT INTO messages(user_id, direction, handle_id, text, status, meta) VALUES (%s, 'out', %s, %s, 'queued', %s) RETURNING id",
             (user_id, handle_id, text, Jsonb(meta or {})), one=True)["id"]


def last_inbound(user_id):
    return q("SELECT * FROM messages WHERE user_id = %s AND direction = 'in' ORDER BY id DESC LIMIT 1", (user_id,), one=True)


def outbound_sends_last_hour(user_id):
    return q("SELECT COUNT(*) AS n FROM messages WHERE user_id = %s AND direction = 'out' AND created_at > now() - interval '1 hour'",
             (user_id,), one=True)["n"]


# ---- jobs ------------------------------------------------------------------------

def enqueue(user_id, type_, payload=None, run_after=None):
    return q("INSERT INTO jobs(user_id, type, payload, run_after) VALUES (%s, %s, %s, COALESCE(%s, now())) RETURNING id",
             (user_id, type_, Jsonb(payload or {}), run_after), one=True)["id"]


def claim_job(worker_id):
    return q("""UPDATE jobs SET status = 'running', locked_at = now(), locked_by = %s, attempts = attempts + 1
                WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND run_after <= now()
                            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING *""", (worker_id,), one=True)


def finish_job(job_id, ok, error=None, retry_in=None):
    if ok:
        q("UPDATE jobs SET status = 'done', finished_at = now(), error = NULL WHERE id = %s", (job_id,))
    elif retry_in is not None:
        q("UPDATE jobs SET status = 'queued', run_after = now() + make_interval(secs => %s), error = %s WHERE id = %s",
          (retry_in, (error or "")[:2000], job_id))
    else:
        q("UPDATE jobs SET status = 'failed', finished_at = now(), error = %s WHERE id = %s", ((error or "")[:2000], job_id))


# ---- usage / spend ----------------------------------------------------------------

def record_usage(user_id, kind, model, input_tokens=0, output_tokens=0, cached_tokens=0, seconds=0.0, job_id=None):
    prices = setting("model_prices") or {}
    p = prices.get(model, {})
    cost = 0.0
    if "in" in p:
        cost = (max(input_tokens - cached_tokens, 0) * p.get("in", 0) + cached_tokens * p.get("cached_in", 0)
                + output_tokens * p.get("out", 0)) / 1_000_000
    if "per_minute" in p:
        cost += seconds / 60 * p["per_minute"]
    q("""INSERT INTO usage(user_id, kind, model, input_tokens, output_tokens, cached_tokens, seconds, cost_usd, job_id)
         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
      (user_id, kind, model, input_tokens, output_tokens, cached_tokens, seconds, cost, job_id))
    return cost


def spend(user_id=None, days=1):
    w = "created_at > now() - make_interval(days => %s)"; p = [days]
    if user_id:
        w += " AND user_id = %s"; p.append(user_id)
    return float(q(f"SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE {w}", p, one=True)["c"])


def spend_ok(user):
    """(ok, reason). Checks per-user daily cap and global daily/monthly caps."""
    cap = float(user_setting(user, "daily_spend_cap_usd") or 0)
    if cap and spend(user["id"], 1) >= cap:
        return False, f"your daily cap (${cap:.2f})"
    if spend(None, 1) >= float(setting("global_daily_cap_usd")):
        return False, "the global daily cap"
    if spend(None, 30) >= float(setting("global_monthly_cap_usd")):
        return False, "the global monthly cap"
    return True, ""


# ---- audit ------------------------------------------------------------------------

def audit(actor_key_id, user_id, action, detail=None):
    q("INSERT INTO audit_log(actor_key_id, user_id, action, detail) VALUES (%s, %s, %s, %s)",
      (actor_key_id, user_id, action, Jsonb(detail or {})))
