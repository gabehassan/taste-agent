"""Relay mode: this Mac is only a transport. chat.db -> server, server -> Messages.app.

Env: TASTE_SERVER_URL, TASTE_TRANSPORT_KEY, TASTE_SELF_HANDLES (which self-chat to watch), TASTE_SEND_TO.
"""
import base64
import logging
import os
import sqlite3
import time
import traceback

import httpx

from . import db, imessage
from .config import CHAT_DB, LOG_PATH, POLL_SECONDS, SELF_HANDLES, SEND_TO

log = logging.getLogger("taste.relay")
SERVER = os.environ.get("TASTE_SERVER_URL", "").rstrip("/")
KEY = os.environ.get("TASTE_TRANSPORT_KEY", "")
HANDLE = os.environ.get("TASTE_HANDLE", SELF_HANDLES[0])
TAPBACK = {2000: "love", 2001: "like", 2002: "dislike", 2003: "laugh", 2004: "emphasize", 2005: "question"}


def client():
    return httpx.Client(base_url=SERVER, headers={"Authorization": f"Bearer {KEY}"}, timeout=60)


def fetch_new_with_reactions(since_rowid):
    """Like imessage.fetch_new but also returns tapbacks (associated_message_type 2000-2005)."""
    chat_ids = imessage.self_chat_ids()
    if not chat_ids:
        return []
    qs = ",".join("?" * len(chat_ids))
    sql = f"""
    SELECT m.ROWID, m.guid, m.date, m.is_from_me, m.text, m.attributedBody, m.cache_has_attachments,
           m.associated_message_type, m.associated_message_guid
    FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
    WHERE j.chat_id IN ({qs}) AND m.ROWID > ? AND m.item_type = 0
    ORDER BY m.ROWID"""
    out = []
    with sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True, timeout=5) as c:
        for rowid, guid, date, from_me, text, body, has_att, amt, aguid in c.execute(sql, (*chat_ids, since_rowid)):
            rec = {"rowid": rowid, "guid": guid, "ts": date / 1e9 + imessage.APPLE_EPOCH, "is_from_me": bool(from_me)}
            if amt in TAPBACK:
                rec.update(kind="reaction", reaction=TAPBACK[amt], target_guid=(aguid or "").split("/")[-1].removeprefix("p:0/"), text="")
            elif amt == 0:
                txt = (text or imessage.decode_body(body) or "").replace(imessage.ATTACHMENT_CHAR, " ").strip()
                rec.update(kind="text", text=txt, attachments=imessage._attachments(c, rowid) if has_att else [])
            else:
                continue
            out.append(rec)
    return out


def guid_of_last_sent(text):
    """Find the guid of the message we just sent (for reaction targeting)."""
    with sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True, timeout=5) as c:
        r = c.execute("SELECT guid FROM message WHERE is_from_me = 1 AND text = ? ORDER BY ROWID DESC LIMIT 1", (text,)).fetchone()
    return r[0] if r else None


def push_inbound(c, m):
    payload = {"handle": HANDLE, "external_id": m["guid"], "ts": m["ts"], "kind": m["kind"], "text": m.get("text", "")}
    if m["kind"] == "reaction":
        payload["reaction"] = m["reaction"]; payload["target_external_id"] = m["target_guid"]
    atts = []
    for a in m.get("attachments", [])[:5]:
        img = imessage.image_bytes(a["path"])
        if img and len(img[1]) <= 6 * 1024 * 1024:
            atts.append({"name": os.path.basename(a["path"]), "content_type": img[0], "data_b64": base64.b64encode(img[1]).decode()})
    payload["attachments"] = atts
    r = c.post("/v1/inbound", json=payload)
    r.raise_for_status()
    return r.json()


def deliver_outbound(c):
    r = c.get("/v1/outbound")
    r.raise_for_status()
    for m in r.json().get("messages", []):
        try:
            if m["kind"] == "reaction":
                ok = False  # tapbacks not supported by AppleScript; server only queues them when we advertise 'react'
                c.post(f"/v1/outbound/{m['id']}/ack", json={"ok": ok, "error": "react unsupported"})
                continue
            db.log_sent(m["text"].strip())
            imessage.send(m["text"], to=SEND_TO)
            time.sleep(1.5)
            c.post(f"/v1/outbound/{m['id']}/ack", json={"ok": True, "external_id": guid_of_last_sent(m["text"].strip())})
            log.info("sent %s: %s", m["id"], m["text"][:80].replace("\n", " / "))
        except Exception as e:
            log.error("send failed for %s: %s", m["id"], e)
            c.post(f"/v1/outbound/{m['id']}/ack", json={"ok": False, "error": str(e)[:300]})


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
    if not SERVER or not KEY:
        raise SystemExit("TASTE_SERVER_URL and TASTE_TRANSPORT_KEY are required for relay mode")
    db.init()
    from .daemon import wait_for_permissions
    wait_for_permissions()
    log.info("relay up -> %s as %s", SERVER, HANDLE)
    said_hello = False
    while True:
        try:
            if not said_hello:
                with client() as c:
                    r = c.post("/v1/transport/hello", json={"handle": HANDLE, "capabilities": []})
                said_hello = r.status_code == 200
                if not said_hello:
                    log.warning("hello failed (%s), will retry", r.status_code)
            since = db.get_state("relay_rowid")
            if since is None:
                since = imessage.max_rowid(); db.set_state("relay_rowid", since)
            echoes = db.recent_sent_texts()
            with client() as c:
                for m in fetch_new_with_reactions(since):
                    db.set_state("relay_rowid", m["rowid"])
                    if m["kind"] == "text" and m["text"].strip() in echoes:
                        continue
                    if time.time() - m["ts"] > 6 * 3600:
                        continue
                    try:
                        res = push_inbound(c, m)
                        log.info("inbound %s -> %s", m["rowid"], res)
                    except Exception as e:
                        log.error("push failed for %s: %s", m["rowid"], e)
                deliver_outbound(c)
        except Exception as e:
            log.error("relay loop: %s\n%s", e, traceback.format_exc())
            time.sleep(10)
        time.sleep(POLL_SECONDS)
