import concurrent.futures
import re
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from tasteserver import db, dispatch, handlers, login
from tasteserver.routes import auth as auth_routes

from .conftest import OTHER, PHONE


def issue_code(user, phone=None):
    mid = login.issue(user, phone)
    text = db.q("SELECT text FROM messages WHERE id = %s", (mid,), one=True)["text"]
    return re.search(r"\b[0-9]{6}\b", text)[0], mid


def test_phone_numbers_need_a_country_code():
    with pytest.raises(ValidationError):
        auth_routes.AuthExchange(token="123456")
    for value in ["", "abc2025550143", "+1+2025550143", "123"]:
        with pytest.raises(HTTPException):
            login.phone_number(value)
    assert login.phone_number("(202) 555-0143") == PHONE


def test_texted_code_is_bound_to_the_phone_and_single_use(make_user):
    user = make_user()
    handlers.do_login_code(user)
    assert db.q("SELECT phone FROM login_challenges", one=True)["phone"] == PHONE
    code = re.search(r"\b[0-9]{6}\b", db.q("SELECT text FROM messages", one=True)["text"])[0]
    assert login.exchange(PHONE, code, "test")["user_id"] == str(user["id"])
    with pytest.raises(HTTPException):
        login.exchange(PHONE, code, "test")


def test_wrong_phone_and_five_guesses(make_user):
    code, _ = issue_code(make_user())
    with pytest.raises(HTTPException):
        login.exchange(OTHER, code, "test")
    for _ in range(5):
        with pytest.raises(HTTPException):
            login.exchange(PHONE, "000000", "test")
    assert db.q("SELECT attempts FROM login_challenges", one=True)["attempts"] == 5
    with pytest.raises(HTTPException):
        login.exchange(PHONE, code, "test")


def test_expired_code_and_disabled_user(make_user):
    user = make_user()
    code, _ = issue_code(user)
    db.q("UPDATE login_challenges SET expires_at = now() - interval '1 second'")
    with pytest.raises(HTTPException):
        login.exchange(PHONE, code, "test")
    code, _ = issue_code(user)
    db.q("UPDATE users SET status = 'disabled'")
    with pytest.raises(HTTPException):
        login.exchange(PHONE, code, "test")
    assert not db.q("SELECT * FROM api_keys")


def test_a_new_code_supersedes_the_undelivered_one(make_user, sent):
    user = make_user()
    with patch.object(login.secrets, "randbelow", return_value=123456):
        _, old = issue_code(user)
        code, _ = issue_code(user)
    assert len(db.q("SELECT * FROM login_challenges")) == 2
    dispatch.run_once()
    assert db.q("SELECT status FROM messages WHERE id = %s", (old,), one=True)["status"] == "cancelled"
    assert sent.call_count == 1
    assert login.exchange(PHONE, code, "test")["user_id"] == str(user["id"])


def test_concurrent_exchanges_create_one_session(make_user):
    code, _ = issue_code(make_user())

    def attempt(_):
        try:
            return login.exchange(PHONE, code, "test")
        except HTTPException:
            return None

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(r is not None for r in results) == 1
    assert len(db.q("SELECT * FROM api_keys")) == 1


def test_requesting_a_code_does_not_reveal_accounts_or_sign_up(make_user, client):
    make_user()
    known = client.post("/v1/auth/request", json={"phone": PHONE})
    unknown = client.post("/v1/auth/request", json={"phone": OTHER})
    assert known.json() == unknown.json()
    assert client.post("/v1/auth/exchange", json={"token": "123456"}).status_code == 422
    assert len(db.q("SELECT * FROM users")) == 1
    assert client.get("/v1/public/config").json()["open_signup"] is False
