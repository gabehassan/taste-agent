"""Phone-bound, single-use login challenges shared by web and message login."""

import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException

from . import auth, blooio, db, ratelimit
from .prompts import copy as C


def phone_number(value):
    raw = (value or "").strip()
    if not re.fullmatch(r"[+\d\s().-]+", raw):
        raise HTTPException(422, "enter a phone number with its country code")
    phone = blooio.normalize(raw)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise HTTPException(422, "enter a phone number with its country code")
    return phone


def _digest(phone, code):
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def issue(user, phone=None, *, deliver=True):
    if phone is None:
        h = db.q(
            "SELECT address FROM handles WHERE user_id = %s AND address LIKE '+%%' ORDER BY last_seen_at DESC NULLS LAST LIMIT 1",
            (user["id"],),
            one=True,
        )
        phone = h["address"] if h else ""
    phone = phone_number(phone)
    ratelimit.hit(f"login_issue:{phone}", 3, 3600)
    with db.transaction():
        active = db.q(
            "SELECT id FROM users WHERE id = %s AND status = 'active' FOR NO KEY UPDATE", (user["id"],), one=True
        )
        handle = db.q("SELECT id FROM handles WHERE user_id = %s AND address = %s", (user["id"], phone), one=True)
        if not active or not handle:
            raise HTTPException(401, "unable to request a code")
        code = str(secrets.randbelow(900000) + 100000)
        db.q("UPDATE login_challenges SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (user["id"],))
        challenge = db.q(
            "INSERT INTO login_challenges(user_id, phone, code_hash, expires_at) VALUES (%s, %s, %s, now() + interval '10 minutes') RETURNING id",
            (user["id"], phone, _digest(phone, code)),
            one=True,
        )
        if not deliver:
            db.audit(None, user["id"], "auth.owner_code", {"delivery": "operator console"})
            return code
        # Auth has its own limit; normal chat traffic must not silently drop login codes.
        return db.queue_outbound(
            user["id"],
            C("login_code", code=code),
            handle_id=handle["id"],
            meta={"to": phone, "login_challenge": str(challenge["id"])},
        )


def exchange(phone, code, ip):
    phone = phone_number(phone)
    code = code.strip().replace(" ", "")
    if not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(422, "enter the six-digit code")
    ratelimit.hit(f"auth_xp:{phone}", 10, 3600)
    result = None
    with db.transaction():
        t = db.q(
            """SELECT * FROM login_challenges WHERE phone = %s AND used_at IS NULL
                    AND expires_at > now() ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
            (phone,),
            one=True,
        )
        if t and t["attempts"] < 5:
            if hmac.compare_digest(t["code_hash"], _digest(phone, code)):
                user = db.q("SELECT id FROM users WHERE id = %s AND status = 'active'", (t["user_id"],), one=True)
                if user:
                    db.q("UPDATE login_challenges SET used_at = now() WHERE id = %s", (t["id"],))
                    raw, kid = auth.create_key(t["user_id"], "web session", ["user"], expires_days=30)
                    db.audit(kid, t["user_id"], "auth.login", {"ip": ip})
                    result = {"key": raw, "user_id": str(t["user_id"]), "expires_days": 30}
            else:
                db.q("UPDATE login_challenges SET attempts = attempts + 1 WHERE id = %s", (t["id"],))
    # Raise after commit so incorrect guesses actually consume an attempt.
    if result is None:
        raise HTTPException(401, "invalid or expired code")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Create a one-time dashboard code without sending a message. Requires server database access."
    )
    parser.add_argument("phone")
    args = parser.parse_args()
    phone = phone_number(args.phone)
    user = db.q(
        "SELECT u.* FROM users u JOIN handles h ON h.user_id=u.id WHERE h.address=%s AND u.status='active'",
        (phone,),
        one=True,
    )
    if not user:
        parser.error("no active account for this phone")
    try:
        print(f"One-time code: {issue(user, phone, deliver=False)} (10 minutes; no message sent)")
    finally:
        db.pool.close()
