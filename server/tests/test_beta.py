"""Regression tests. TEST_DATABASE_URL creates and removes an isolated test schema.
No model calls or real messages are made. Without it, only pure tests run.
"""
import concurrent.futures
import hashlib
import datetime as dt
import json
import os
import pathlib
import re
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@localhost/unused")

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tasteserver import api, blooio, db, dispatch, handlers, login, memory, scheduler, brain

PHONE = "+13135550123"
OTHER = "+13135550124"


def event(text="hello", sender=PHONE, eid=None, attachments=None):
    return {"id": eid or str(uuid.uuid4()), "type": "message.received", "data": {
        "sender": sender, "text": text, "id": str(uuid.uuid4()), "chat_id": "chat_test", "attachments": attachments or []}}


class PureTests(unittest.TestCase):
    def test_missing_phone_rejected(self):
        with self.assertRaises(ValidationError):
            api.AuthExchange(token="123456")
        for value in ["", "abc3135550123", "+1+3135550123", "123"]:
            with self.assertRaises(HTTPException):
                login.phone_number(value)
        self.assertEqual(login.phone_number("(313) 555-0123"), PHONE)

    def test_retry_policy(self):
        def error(status, code, headers=None):
            return blooio.SendError(httpx.Response(status, json={"error": {"code": code}}, headers=headers))
        self.assertEqual(dispatch.retry_delay(error(503, "unavailable"), 1), 15)
        self.assertEqual(dispatch.retry_delay(error(429, "rate_limited", {"Retry-After": "60"}), 1), 60)
        self.assertIsNone(dispatch.retry_delay(error(429, "rate_limited"), 1))
        self.assertIsNone(dispatch.retry_delay(error(429, "conversation_awaiting_reply", {"Retry-After": "60"}), 1))
        self.assertIsNone(dispatch.retry_delay(error(403, "conversation_content_restricted"), 1))
        self.assertIsNone(dispatch.retry_delay(httpx.ReadTimeout("timeout"), 5))

    def test_idempotency_header_and_frozen_sender(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(202, json={"id": "accepted"})
        with patch.object(blooio, "_c", side_effect=lambda: httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(respond))):
            blooio.send_text(PHONE, "hello", idempotency_key="stable-key", from_number=OTHER)
        self.assertEqual(requests[0].headers["Idempotency-Key"], "stable-key")
        self.assertIn(OTHER, requests[0].content.decode())


class ClientIpTests(unittest.TestCase):
    def request(self, headers):
        from starlette.requests import Request
        scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()], "client": ("10.0.0.9", 1234)}
        return Request(scope)

    def test_forwarded_for_is_never_trusted(self):
        from tasteserver import ratelimit
        self.assertEqual(ratelimit.client_ip(self.request({"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})), "5.6.7.8")
        self.assertEqual(ratelimit.client_ip(self.request({"X-Forwarded-For": "1.2.3.4"})), "10.0.0.9")

    def test_dashboard_forwarding_needs_the_secret(self):
        from tasteserver import ratelimit
        with patch.object(ratelimit, "DASHBOARD_PROXY_SECRET", "s3cret"):
            forged = {"X-Taste-Client-IP": "1.1.1.1", "X-Taste-Proxy-Secret": "guess", "X-Real-IP": "5.6.7.8"}
            self.assertEqual(ratelimit.client_ip(self.request(forged)), "5.6.7.8")
            signed = {**forged, "X-Taste-Proxy-Secret": "s3cret"}
            self.assertEqual(ratelimit.client_ip(self.request(signed)), "1.1.1.1")
        with patch.object(ratelimit, "DASHBOARD_PROXY_SECRET", ""):
            self.assertEqual(ratelimit.client_ip(self.request({"X-Taste-Client-IP": "1.1.1.1", "X-Taste-Proxy-Secret": ""})), "10.0.0.9")


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "set TEST_DATABASE_URL for isolated PostgreSQL integration tests")
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ["TEST_DATABASE_URL"]
        cls.schema = "taste_test_" + uuid.uuid4().hex
        cls.admin = psycopg.connect(cls.url, autocommit=True)
        cls.admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.original_pool = db.pool
        db.pool = ConnectionPool(conninfo=cls.url, min_size=1, max_size=6,
                                 kwargs={"row_factory": dict_row, "options": f"-c search_path={cls.schema},public"})
        script = (pathlib.Path(db.__file__).parent / "schema.sql").read_text().replace("CREATE EXTENSION IF NOT EXISTS pgcrypto;", "")
        with db.conn() as c:
            c.execute(script)
            for k, v in api.__dict__["db"].DEFAULT_SETTINGS.items():
                c.execute("INSERT INTO settings(key,value) VALUES (%s,%s)", (k, db.J(v)))

    @classmethod
    def tearDownClass(cls):
        db.pool.close()
        db.pool = cls.original_pool
        cls.admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))
        cls.admin.close()

    def setUp(self):
        db.q("TRUNCATE users, webhook_events, rate_limits CASCADE")
        db.set_setting("open_signup", False)
        self.patches = [patch.object(blooio, "send_text", return_value={"id": "sent_test", "chat_id": "chat_test", "status": "queued"}),
                        patch.object(blooio, "typing"), patch.object(blooio, "enabled", return_value=True),
                        patch.object(blooio, "NUMBER", OTHER), patch.object(dispatch.time, "sleep")]
        self.send = self.patches[0].start()
        for p in self.patches[1:]: p.start()
        for p in self.patches: self.addCleanup(p.stop)

    def user(self, phone=PHONE):
        u = db.q("INSERT INTO users(transport) VALUES ('blooio') RETURNING *", one=True)
        db.q("INSERT INTO handles(user_id,address) VALUES (%s,%s)", (u["id"], phone))
        return u

    def code(self, u, phone=None):
        mid = login.issue(u, phone)
        m = db.q("SELECT * FROM messages WHERE id=%s", (mid,), one=True)
        return re.search(r"\b[0-9]{6}\b", m["text"])[0], mid

    def test_text_login_binds_phone_and_is_single_use(self):
        u = self.user()
        handlers.do_login_link(u)
        row = db.q("SELECT * FROM login_challenges", one=True)
        self.assertEqual(row["phone"], PHONE)
        code = re.search(r"\b[0-9]{6}\b", db.q("SELECT text FROM messages", one=True)["text"])[0]
        result = login.exchange(PHONE, code, "test")
        self.assertEqual(result["user_id"], str(u["id"]))
        with self.assertRaises(HTTPException): login.exchange(PHONE, code, "test")

    def test_wrong_phone_and_five_guesses(self):
        u = self.user()
        code, _ = self.code(u)
        with self.assertRaises(HTTPException): login.exchange(OTHER, code, "test")
        for _ in range(5):
            with self.assertRaises(HTTPException): login.exchange(PHONE, "000000", "test")
        self.assertEqual(db.q("SELECT attempts FROM login_challenges", one=True)["attempts"], 5)
        with self.assertRaises(HTTPException): login.exchange(PHONE, code, "test")

    def test_expired_and_disabled_user(self):
        u = self.user()
        code, _ = self.code(u)
        db.q("UPDATE login_challenges SET expires_at = now() - interval '1 second'")
        with self.assertRaises(HTTPException): login.exchange(PHONE, code, "test")
        code, _ = self.code(u)
        db.q("UPDATE users SET status='disabled'")
        with self.assertRaises(HTTPException): login.exchange(PHONE, code, "test")
        self.assertFalse(db.q("SELECT * FROM api_keys"))

    def test_code_reuse_and_superseded_delivery(self):
        u = self.user()
        with patch.object(login.secrets, "randbelow", return_value=123456):
            _, old = self.code(u)
            code, new = self.code(u)
        self.assertEqual(len(db.q("SELECT * FROM login_challenges")), 2)
        dispatch.run_once()
        self.assertEqual(db.q("SELECT status FROM messages WHERE id=%s", (old,), one=True)["status"], "cancelled")
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(login.exchange(PHONE, code, "test")["user_id"], str(u["id"]))

    def test_two_simultaneous_exchanges_only_one_session(self):
        code, _ = self.code(self.user())
        def attempt(_):
            try: return login.exchange(PHONE, code, "test")
            except HTTPException: return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(db.q("SELECT * FROM api_keys")), 1)

    def test_public_request_does_not_enumerate_or_signup(self):
        self.user()
        client = TestClient(api.app)
        known = client.post("/v1/auth/request", json={"phone": PHONE})
        unknown = client.post("/v1/auth/request", json={"phone": OTHER})
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(client.post("/v1/auth/exchange", json={"token":"123456"}).status_code, 422)
        self.assertEqual(len(db.q("SELECT * FROM users")), 1)
        self.assertFalse(client.get("/v1/public/config").json()["open_signup"])

    def test_oversized_bodies_rejected_with_or_without_length(self):
        client = TestClient(api.app)
        too_big = b"x" * (api.MAX_BODY_BYTES + 1)
        self.assertEqual(client.post("/v1/inbound", content=too_big).status_code, 413)
        self.assertEqual(client.post("/v1/inbound", content=iter([too_big[:4_000_000], too_big[4_000_000:]])).status_code, 413)
        self.assertEqual(client.post("/v1/inbound", content=b"{}", headers={"Content-Length": "abc"}).status_code, 413)

    def test_first_link_and_duplicate_webhook(self):
        db.set_setting("open_signup", True)
        ev = event("https://example.com/article")
        first = api.process_blooio_event(ev)
        self.assertIn("job_id", first)
        self.assertTrue(api.process_blooio_event(ev)["duplicate"])
        self.assertEqual(db.q("SELECT text FROM messages WHERE direction='in'", one=True)["text"], ev["data"]["text"])
        self.assertEqual(len(db.q("SELECT * FROM users")), 1)
        self.assertEqual(len(db.q("SELECT * FROM jobs")), 1)

    def test_first_attachment(self):
        db.set_setting("open_signup", True)
        ev = event("", attachments=[{"url": "https://example.com/photo.jpg", "content_type": "image/jpeg"}])
        with patch.object(api, "_store_remote_attachments", return_value=[{"key": "test/photo.jpg", "content_type":"image/jpeg"}]):
            api.process_blooio_event(ev)
        self.assertTrue(db.q("SELECT attachments FROM messages WHERE direction='in'", one=True)["attachments"])

    def test_failure_rolls_back_receipt_and_onboarding(self):
        db.set_setting("open_signup", True)
        ev = event("https://example.com/article")
        with patch.object(db, "enqueue", side_effect=RuntimeError("test fault")):
            with self.assertRaises(RuntimeError): api.process_blooio_event(ev)
        self.assertFalse(db.q("SELECT * FROM users"))
        self.assertFalse(db.q("SELECT * FROM webhook_events"))
        self.assertIn("job_id", api.process_blooio_event(ev))

    def test_invite_preserves_attached_link_and_is_single_use(self):
        code = "test_invitation_123456789"
        db.q("INSERT INTO invites(token_hash,expires_at) VALUES (%s,now()+interval '1 day')", (hashlib.sha256(code.encode()).hexdigest(),))
        api.process_blooio_event(event(code + " https://example.com/article"))
        self.assertEqual(db.q("SELECT text FROM messages WHERE direction='in'", one=True)["text"], "https://example.com/article")
        self.assertTrue(api.process_blooio_event(event(code, sender=OTHER))["unknown"])
        self.assertEqual(len(db.q("SELECT * FROM users")), 1)

    def test_concurrent_new_messages_create_one_account(self):
        db.set_setting("open_signup", True)
        events = [event("one"), event("two")]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(pool.map(api.process_blooio_event, events))
        self.assertEqual(len(db.q("SELECT * FROM users")), 1)
        self.assertEqual(len(db.q("SELECT * FROM jobs")), 2)

    def test_temporary_send_failure_retries_same_bubble(self):
        u = self.user()
        mid = db.queue_outbound(u["id"], "first\n\nsecond")
        self.send.side_effect = [{"id":"first"}, httpx.ReadTimeout("test timeout"), {"id":"second"}]
        dispatch.run_once()
        self.assertEqual(db.q("SELECT status FROM messages WHERE id=%s", (mid,), one=True)["status"], "queued")
        db.q("UPDATE messages SET send_after=now()")
        dispatch.run_once()
        calls = self.send.call_args_list
        self.assertEqual([c.args[1] for c in calls], ["first", "second", "second"])
        self.assertEqual(calls[1].kwargs["idempotency_key"], calls[2].kwargs["idempotency_key"])
        self.assertEqual(db.q("SELECT status FROM messages WHERE id=%s", (mid,), one=True)["status"], "sent")

    def test_expired_code_not_sent(self):
        _, mid = self.code(self.user())
        db.q("UPDATE login_challenges SET expires_at=now()-interval '1 second'")
        dispatch.run_once()
        self.send.assert_not_called()
        self.assertEqual(db.q("SELECT status FROM messages WHERE id=%s", (mid,), one=True)["status"], "cancelled")

    def test_crashed_send_recovers(self):
        u = self.user()
        mid = db.queue_outbound(u["id"], "recover me")
        db.q("UPDATE messages SET status='sending',send_attempts=1,send_locked_at=now()-interval '6 minutes' WHERE id=%s", (mid,))
        dispatch.run_once()
        self.assertEqual(db.q("SELECT status FROM messages WHERE id=%s", (mid,), one=True)["status"], "sent")

    def item(self, user, title="a quiet room"):
        return db.add_item(user["id"], title=title, kind="essay", summary="on space and attention",
                           snippets=["A room can make room for a thought."], tags=["design"], read_minutes=5)

    def test_memory_and_feedback_are_isolated(self):
        a,b=self.user(),self.user(OTHER)
        memory.remember(a["id"], "I love quiet interiors.")
        item=self.item(a)
        self.assertEqual(len(memory.memories(a["id"])),1)
        self.assertEqual(memory.memories(b["id"]),[])
        with self.assertRaises(HTTPException): memory.feedback(b["id"],item,"finished")
        memory.feedback(a["id"],item,"finished")
        memory.feedback(a["id"],item,"finished")
        self.assertEqual(len(db.q("SELECT * FROM item_events")),1)
        self.assertEqual(memory.daily(a["id"],"2026-09-12")["picks"],[])
        self.assertEqual(memory.daily(a["id"],"2026-09-12")["finished_week"],1)

    def test_all_explicit_memories_are_valid_json(self):
        u=self.user()
        for i in range(30): memory.remember(u["id"],str(i)+"x"*490)
        self.assertEqual(len(json.loads(memory.context(u["id"]))),30)
        with self.assertRaises(HTTPException): memory.remember(u["id"],"one too many")

    def test_daily_picks_stable_and_snooze_respected(self):
        u=self.user()
        for i in range(4): self.item(u,str(i))
        first=memory.daily(u["id"],"2026-09-12")["picks"]
        self.assertEqual(first,memory.daily(u["id"],"2026-09-12")["picks"])
        iid=first[0]["item"]["id"]
        memory.feedback(u["id"],iid,"later")
        self.assertNotIn(iid,[p["item"]["id"] for p in memory.daily(u["id"],"2026-09-12")["picks"]])
        self.assertNotIn(iid,[i["id"] for i in scheduler.proactive_candidates(u)])

    def test_proactive_silence_and_grounded_excerpt(self):
        u=self.user();iid=self.item(u)
        choice=brain.ProactiveChoice(send=False,item_id=0,excerpt_index=0,connection="",reason="no concrete connection")
        with patch.object(brain,"proactive_choice",return_value=choice):
            self.assertIsNone(handlers.do_proactive(u))
        self.assertFalse(db.q("SELECT * FROM messages"))
        choice=brain.ProactiveChoice(send=True,item_id=iid,excerpt_index=0,connection="this connects to your interest in interiors.",reason="explicit interest")
        with patch.object(brain,"proactive_choice",return_value=choice):
            mid=handlers.do_proactive(u)
        row=db.q("SELECT * FROM messages WHERE id=%s",(mid,),one=True)
        self.assertIn("A room can make room for a thought.",row["text"])
        self.assertIn(f"/items/{iid}",row["text"])
        self.assertTrue(row["meta"]["proactive"])
        self.assertEqual(row["meta"]["item_id"],iid)

    def test_proactive_rejects_other_users_item(self):
        a,b=self.user(),self.user(OTHER)
        self.item(a); other=self.item(b)
        choice=brain.ProactiveChoice(send=True,item_id=other,excerpt_index=0,connection="test",reason="test")
        with patch.object(brain,"proactive_choice",return_value=choice):
            self.assertIsNone(handlers.do_proactive(a))
        self.assertFalse(db.q("SELECT * FROM messages"))

    def test_two_unanswered_suggestions_wait_for_engagement(self):
        u=self.user();iid=self.item(u)
        for _ in range(2):
            mid=db.queue_outbound(u["id"],"a suggestion")
            db.q("UPDATE messages SET meta='{\"proactive\":true}',status='sent' WHERE id=%s",(mid,))
        self.assertFalse(scheduler.attention_available(u))
        memory.feedback(u["id"],iid,"later")
        self.assertTrue(scheduler.attention_available(u))

    def test_due_slot_obeys_current_quiet_hours(self):
        u=self.user()
        db.set_user_state(u["id"],plan={"date":"2026-09-12","slots":[{"at":"2026-09-12T12:00:00-04:00","done":False}]})
        with patch.object(scheduler,"_now",return_value=dt.datetime.fromisoformat("2026-09-12T23:00:00-04:00")):
            self.assertIsNone(scheduler.due_slot(u))
        with patch.object(scheduler,"_now",return_value=dt.datetime.fromisoformat("2026-09-12T14:00:00-04:00")):
            self.assertEqual(scheduler.due_slot(u),0)

    def test_pause_cancels_queued_proactive_message(self):
        u=self.user();iid=self.item(u)
        mid=db.queue_outbound(u["id"],"a suggestion")
        db.q("UPDATE messages SET meta=%s WHERE id=%s",(db.J({"proactive":True,"item_id":iid}),mid))
        db.q("UPDATE users SET settings='{\"paused\":true}' WHERE id=%s",(u["id"],))
        dispatch.run_once()
        self.send.assert_not_called()
        self.assertEqual(db.q("SELECT status FROM messages WHERE id=%s",(mid,),one=True)["status"],"cancelled")


if __name__ == "__main__":
    unittest.main()
