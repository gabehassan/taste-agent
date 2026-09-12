"""Blooio transport: hosted iMessage number. Outbound via REST, inbound via signed webhook."""
import hashlib
import hmac
import logging
import os
import re
import time
from urllib.parse import quote

import httpx

log = logging.getLogger("taste.blooio")
BASE = "https://api.blooio.com/v4"
KEY = os.environ.get("BLOOIO_API_KEY", "")
NUMBER = os.environ.get("BLOOIO_NUMBER", "")
SECRET = os.environ.get("BLOOIO_WEBHOOK_SECRET", "")
REACTIONS = {"love", "like", "dislike", "laugh", "emphasize", "question"}


def enabled():
    return bool(KEY and NUMBER)


def _c():
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"}, timeout=30)


def normalize(phone):
    p = re.sub(r"[^\d+]", "", phone or "")
    if p and not p.startswith("+"):
        p = "+1" + p if len(p) == 10 else "+" + p
    return p


def send_text(to, text, reply_to=None, effect=None):
    body = {"to": to, "from": NUMBER, "text": text}
    if reply_to:
        body["reply_to"] = reply_to
    if effect:
        body["effect"] = effect
    with _c() as c:
        r = c.post("/messages", json=body)
    if r.status_code >= 300:
        raise RuntimeError(f"blooio send {r.status_code}: {r.text[:200]}")
    return r.json()  # id, chat_id, protocol


def typing(chat_id, on=True):
    if not chat_id:
        return
    try:
        with _c() as c:
            c.post(f"/chats/{quote(chat_id, safe='')}/typing", json={"state": "started" if on else "stopped"})
    except Exception as e:
        log.info("typing failed: %s", e)


def mark_read(chat_id):
    if not chat_id:
        return
    try:
        with _c() as c:
            c.post(f"/chats/{quote(chat_id, safe='')}/read", json={})
    except Exception as e:
        log.info("read failed: %s", e)


def react(chat_id, message_id, reaction):
    """reaction: love|like|dislike|laugh|emphasize|question or a single emoji."""
    if not (chat_id and message_id and reaction):
        return False
    r_ = reaction if reaction in REACTIONS or len(reaction) <= 2 else "love"
    with _c() as c:
        r = c.post(f"/chats/{quote(chat_id, safe='')}/messages/{quote(message_id, safe='')}/reactions", json={"reaction": f"+{r_}"})
    if r.status_code >= 300:
        log.info("react failed %s: %s", r.status_code, r.text[:160])
        return False
    return True


def verify(raw_body: bytes, header: str, tolerance=300):
    """X-Blooio-Signature: t=<ts>,v1=<hmac_sha256(secret, f"{ts}.{body}")>"""
    if not SECRET or not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts) / (1000 if len(ts) > 10 else 1)) > tolerance:
            return False
    except ValueError:
        return False
    expected = hmac.new(SECRET.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def parse_event(evt):
    """Normalise a Blooio webhook envelope into our inbound shape, or None if not for us."""
    t = evt.get("type", "")
    d = evt.get("data") or {}
    if t == "message.received" or (t.startswith("message.") and d.get("direction") == "inbound" and d.get("kind") == "received"):
        sender = d.get("sender") or (d.get("contact") or {}).get("identifier") or ""
        atts = []
        for a in d.get("attachments") or []:
            url = a.get("url") or a.get("download_url")
            ct = a.get("content_type") or a.get("mime_type") or ""
            if url:
                atts.append({"url": url, "content_type": ct, "name": a.get("filename") or a.get("name") or "file"})
        return {"kind": "text", "sender": normalize(sender), "text": d.get("text") or "", "message_id": d.get("message_id") or d.get("id"),
                "chat_id": d.get("chat_id"), "attachments": atts, "event_id": evt.get("id")}
    if "reaction" in t:
        reaction = (d.get("reaction") or d.get("emoji") or "").lstrip("+")
        if not reaction or (d.get("reaction") or "").startswith("-"):
            return None
        sender = d.get("sender") or (d.get("contact") or {}).get("identifier") or ""
        return {"kind": "reaction", "sender": normalize(sender), "reaction": reaction if reaction in REACTIONS else "love",
                "target_message_id": d.get("target_message_id") or d.get("message_id"), "chat_id": d.get("chat_id"), "event_id": evt.get("id")}
    return None


def split_bubbles(text, max_parts=3):
    """Poke-style bursts: split on blank lines into a few short bubbles. Long texts stay whole."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) <= 1 or len(parts) > max_parts or any(len(p) > 320 for p in parts) or "http" in text and len(parts) > 2:
        return [text]
    return parts
