import datetime as dt

from fastapi import HTTPException

from . import db


def hit(key, limit, window_seconds):
    """Fixed-window counter in Postgres. Raises 429 when over the limit."""
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.datetime.fromtimestamp((int(now.timestamp()) // window_seconds) * window_seconds, dt.timezone.utc)
    r = db.q("""INSERT INTO rate_limits(key, window_start, count) VALUES (%s, %s, 1)
                ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limits.count + 1 RETURNING count""",
             (key, start), one=True)
    if r["count"] > limit:
        retry = int((start + dt.timedelta(seconds=window_seconds) - now).total_seconds()) + 1
        raise HTTPException(429, f"rate limit: {key.split(':')[0]}", headers={"Retry-After": str(retry)})
    return r["count"]


def check(key, limit, window_seconds):
    """Same as hit() but returns False instead of raising (for worker-side gates)."""
    try:
        hit(key, limit, window_seconds)
        return True
    except HTTPException:
        return False


def cleanup():
    db.q("DELETE FROM rate_limits WHERE window_start < now() - interval '2 days'")
