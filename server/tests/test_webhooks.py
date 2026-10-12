import concurrent.futures
import hashlib
import uuid
from unittest.mock import patch

import pytest

from tasteserver import db
from tasteserver.routes import webhooks

from .conftest import OTHER, PHONE


def event(text="hello", sender=PHONE, attachments=None):
    data = {
        "sender": sender,
        "text": text,
        "id": str(uuid.uuid4()),
        "chat_id": "chat_test",
        "attachments": attachments or [],
    }
    return {"id": str(uuid.uuid4()), "type": "message.received", "data": data}


@pytest.fixture
def open_signup(sent):
    db.set_setting("open_signup", True)


def test_first_link_is_kept_and_redelivery_is_a_no_op(open_signup):
    ev = event("https://example.com/article")
    assert "job_id" in webhooks.process_blooio_event(ev)
    assert webhooks.process_blooio_event(ev)["duplicate"] is True
    assert db.q("SELECT text FROM messages WHERE direction = 'in'", one=True)["text"] == ev["data"]["text"]
    assert len(db.q("SELECT * FROM users")) == 1
    assert len(db.q("SELECT * FROM jobs")) == 1


def test_first_message_can_be_a_photo(open_signup):
    ev = event("", attachments=[{"url": "https://example.com/photo.jpg", "content_type": "image/jpeg"}])
    stored = [{"key": "test/photo.jpg", "content_type": "image/jpeg"}]
    with patch.object(webhooks, "_store_remote_attachments", return_value=stored):
        webhooks.process_blooio_event(ev)
    assert db.q("SELECT attachments FROM messages WHERE direction = 'in'", one=True)["attachments"]


def test_a_failure_rolls_back_the_receipt_and_the_new_account(open_signup):
    ev = event("https://example.com/article")
    with patch.object(db, "enqueue", side_effect=RuntimeError("test fault")), pytest.raises(RuntimeError):
        webhooks.process_blooio_event(ev)
    assert not db.q("SELECT * FROM users")
    assert not db.q("SELECT * FROM webhook_events")
    assert "job_id" in webhooks.process_blooio_event(ev)


def test_invite_code_is_single_use_and_keeps_the_rest_of_the_message(sent):
    code = "test_invitation_123456789"
    db.q(
        "INSERT INTO invites(token_hash, expires_at) VALUES (%s, now() + interval '1 day')",
        (hashlib.sha256(code.encode()).hexdigest(),),
    )
    webhooks.process_blooio_event(event(code + " https://example.com/article"))
    assert db.q("SELECT text FROM messages WHERE direction = 'in'", one=True)["text"] == "https://example.com/article"
    assert webhooks.process_blooio_event(event(code, sender=OTHER))["unknown"] is True
    assert len(db.q("SELECT * FROM users")) == 1


def test_strangers_get_one_invite_only_reply_a_day(sent):
    webhooks.process_blooio_event(event("hello?", sender=OTHER))
    webhooks.process_blooio_event(event("anyone?", sender=OTHER))
    assert sent.call_count == 1
    assert not db.q("SELECT * FROM users")


def test_concurrent_first_messages_create_one_account(open_signup):
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        list(pool.map(webhooks.process_blooio_event, [event("one"), event("two")]))
    assert len(db.q("SELECT * FROM users")) == 1
    assert len(db.q("SELECT * FROM jobs")) == 2
