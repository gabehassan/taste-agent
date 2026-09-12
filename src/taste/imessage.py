"""iMessage transport: read new messages from chat.db, send via AppleScript.

This is the only file that knows about iMessage. Swap it for a hosted
provider (Sendblue, Blooio, ...) by reimplementing fetch_new() and send().
"""
import pathlib
import re
import sqlite3
import subprocess
import time

from .config import CHAT_DB, SELF_HANDLES, SEND_TO

APPLE_EPOCH = 978307200
ATTACHMENT_CHAR = "￼"


def decode_body(blob):
    """attributedBody is an Apple typedstream archive. Fast path first."""
    if not blob:
        return None
    try:
        s = blob.split(b"NSString")[1][5:]
        if s[0] == 0x81:
            n = int.from_bytes(s[1:3], "little")
            s = s[3:]
        else:
            n = s[0]
            s = s[1:]
        return s[:n].decode("utf-8")
    except Exception:
        pass
    try:
        from typedstream.stream import TypedStreamReader

        for event in TypedStreamReader.from_data(blob):
            if isinstance(event, bytes):
                return event.decode("utf-8", errors="replace")
    except Exception:
        return None
    return None


def _connect():
    return sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True, timeout=5)


def self_chat_ids():
    qs = ",".join("?" * len(SELF_HANDLES))
    with _connect() as c:
        rows = c.execute(f"SELECT ROWID FROM chat WHERE chat_identifier IN ({qs})", SELF_HANDLES)
        return [r[0] for r in rows]


def max_rowid():
    with _connect() as c:
        return c.execute("SELECT COALESCE(MAX(ROWID),0) FROM message").fetchone()[0]


def fetch_new(since_rowid):
    """Messages in the self chat(s) with ROWID > since_rowid, oldest first."""
    chat_ids = self_chat_ids()
    if not chat_ids:
        return []
    qs = ",".join("?" * len(chat_ids))
    sql = f"""
    SELECT m.ROWID, m.date, m.is_from_me, m.text, m.attributedBody, m.cache_has_attachments
    FROM message m
    JOIN chat_message_join j ON j.message_id = m.ROWID
    WHERE j.chat_id IN ({qs}) AND m.ROWID > ?
      AND m.item_type = 0 AND m.associated_message_type = 0
    ORDER BY m.ROWID
    """
    out = []
    with _connect() as c:
        for rowid, date, from_me, text, body, has_att in c.execute(sql, (*chat_ids, since_rowid)):
            txt = text or decode_body(body) or ""
            txt = txt.replace(ATTACHMENT_CHAR, " ").strip()
            atts = _attachments(c, rowid) if has_att else []
            out.append(
                {
                    "rowid": rowid,
                    "ts": date / 1e9 + APPLE_EPOCH,
                    "is_from_me": bool(from_me),
                    "text": txt,
                    "attachments": atts,
                }
            )
    return out


def _attachments(c, msg_rowid):
    rows = c.execute(
        """SELECT a.filename, a.mime_type FROM attachment a
           JOIN message_attachment_join j ON j.attachment_id = a.ROWID
           WHERE j.message_id = ?""",
        (msg_rowid,),
    )
    out = []
    for filename, mime in rows:
        if not filename:
            continue
        p = pathlib.Path(filename.replace("~", str(pathlib.Path.home()), 1))
        out.append({"path": str(p), "mime": mime or ""})
    return out


def image_bytes(path):
    """Return (media_type, bytes) for an image attachment, converting HEIC to JPEG."""
    p = pathlib.Path(path)
    if not p.exists():
        return None
    ext = p.suffix.lower()
    if ext in (".heic", ".heif", ".tiff", ".tif", ".bmp"):
        out = pathlib.Path("/tmp") / (p.stem + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", str(p), "--out", str(out)],
                       capture_output=True, check=False)
        if not out.exists():
            return None
        return "image/jpeg", out.read_bytes()
    media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".gif": "image/gif", ".webp": "image/webp"}.get(ext)
    if not media:
        return None
    return media, p.read_bytes()


def _as_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def send(text, to=SEND_TO):
    """Send an iMessage via Messages.app. Returns True on success."""
    text = text.strip()
    if not text:
        return False
    script = (
        'tell application "Messages"\n'
        '  set svc to 1st account whose service type = iMessage\n'
        f'  set theBuddy to participant "{_as_escape(to)}" of svc\n'
        f'  send "{_as_escape(text)}" to theBuddy\n'
        "end tell"
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"osascript failed: {r.stderr.strip()}")
    return True


URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")


def extract_urls(text):
    return [u.rstrip(".,;:!?") for u in URL_RE.findall(text or "")]
