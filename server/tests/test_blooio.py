import hashlib
import hmac
import time
from unittest.mock import patch

import httpx

from tasteserver import blooio, dispatch

from .conftest import OTHER, PHONE


def send_error(status, code, headers=None):
    return blooio.SendError(httpx.Response(status, json={"error": {"code": code}}, headers=headers))


def test_retry_policy():
    assert dispatch.retry_delay(send_error(503, "unavailable"), 1) == 15
    assert dispatch.retry_delay(send_error(429, "rate_limited", {"Retry-After": "60"}), 1) == 60
    assert dispatch.retry_delay(send_error(429, "rate_limited"), 1) is None
    assert dispatch.retry_delay(send_error(429, "conversation_awaiting_reply", {"Retry-After": "60"}), 1) is None
    assert dispatch.retry_delay(send_error(403, "conversation_content_restricted"), 1) is None
    assert dispatch.retry_delay(httpx.ReadTimeout("timeout"), 5) is None


def test_idempotency_key_and_frozen_sender():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(202, json={"id": "accepted"})

    def client():
        return httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(respond))

    with patch.object(blooio, "_c", side_effect=client):
        blooio.send_text(PHONE, "hello", idempotency_key="stable-key", from_number=OTHER)
    assert requests[0].headers["Idempotency-Key"] == "stable-key"
    assert OTHER in requests[0].content.decode()


def sign(body, ts, secret="whsec"):
    return f"t={ts},v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def test_webhook_signature():
    body = b'{"type":"message.received"}'
    now = int(time.time())
    with patch.object(blooio, "SECRET", "whsec"):
        assert blooio.verify(body, sign(body, now))
        assert blooio.verify(body, sign(body, now * 1000))
        assert not blooio.verify(body + b" ", sign(body, now))
        assert not blooio.verify(body, sign(body, now, secret="other"))
        assert not blooio.verify(body, sign(body, now - 3600))
        assert not blooio.verify(body, "garbage")
    with patch.object(blooio, "SECRET", ""):
        assert not blooio.verify(body, sign(body, now, secret=""))


def test_parse_events():
    text = blooio.parse_event(
        {
            "id": "evt_1",
            "type": "message.received",
            "data": {
                "sender": "(202) 555-0143",
                "text": "hi",
                "message_id": "m1",
                "chat_id": "c1",
                "attachments": [{"url": "https://cdn.example/a.jpg", "mime_type": "image/jpeg"}],
            },
        }
    )
    assert text["kind"] == "text" and text["sender"] == PHONE and text["attachments"][0]["content_type"] == "image/jpeg"
    added = blooio.parse_event({"id": "e", "type": "message.reaction", "data": {"sender": PHONE, "reaction": "+laugh"}})
    assert added["kind"] == "reaction" and added["reaction"] == "laugh"
    assert blooio.parse_event({"type": "message.reaction", "data": {"sender": PHONE, "reaction": "-love"}}) is None
    assert blooio.parse_event({"type": "number.updated", "data": {}}) is None


def test_split_bubbles():
    assert blooio.split_bubbles("first\n\nsecond") == ["first", "second"]
    assert blooio.split_bubbles("one paragraph") == ["one paragraph"]
    assert blooio.split_bubbles("a\n\nb\n\nc\n\nd") == ["a\n\nb\n\nc\n\nd"]
    assert blooio.split_bubbles("short\n\n" + "x" * 400) == ["short\n\n" + "x" * 400]
