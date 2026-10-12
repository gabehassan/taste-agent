"""Helpers shared by the route modules."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from .. import db, ratelimit
from ..auth import Principal


def key_rate_limit(p: Principal):
    ratelimit.hit(f"key:{p.key_id}", int(db.setting("rate_key_per_hour")), 3600)


# Raster formats the vision model accepts. SVG and other image/* types are refused: they can carry script
# and would be served back from the bucket with their original content type.
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp", "image/heic": "heic"}


def clean_row(row):
    if row is None:
        return None
    d = dict(row)
    d.pop("tsv", None)
    d.pop("key_hash", None)
    return d


def check_tz(tz):
    try:
        ZoneInfo(tz)
    except (ValueError, ZoneInfoNotFoundError):
        raise HTTPException(400, "unknown time zone") from None
