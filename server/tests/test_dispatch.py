import httpx

from tasteserver import db, dispatch, login


def status(mid):
    return db.q("SELECT status FROM messages WHERE id = %s", (mid,), one=True)["status"]


def test_temporary_failure_retries_the_same_bubble_with_the_same_key(make_user, sent):
    user = make_user()
    mid = db.queue_outbound(user["id"], "first\n\nsecond")
    sent.side_effect = [{"id": "first"}, httpx.ReadTimeout("test timeout"), {"id": "second"}]
    dispatch.run_once()
    assert status(mid) == "queued"
    db.q("UPDATE messages SET send_after = now()")
    dispatch.run_once()
    calls = sent.call_args_list
    assert [c.args[1] for c in calls] == ["first", "second", "second"]
    assert calls[1].kwargs["idempotency_key"] == calls[2].kwargs["idempotency_key"]
    assert status(mid) == "sent"


def test_expired_login_code_is_never_sent(make_user, sent):
    mid = login.issue(make_user())
    db.q("UPDATE login_challenges SET expires_at = now() - interval '1 second'")
    dispatch.run_once()
    sent.assert_not_called()
    assert status(mid) == "cancelled"


def test_send_interrupted_by_a_crash_is_recovered(make_user):
    mid = db.queue_outbound(make_user()["id"], "recover me")
    db.q(
        "UPDATE messages SET status = 'sending', send_attempts = 1, send_locked_at = now() - interval '6 minutes' WHERE id = %s",
        (mid,),
    )
    dispatch.run_once()
    assert status(mid) == "sent"


def test_pausing_cancels_a_queued_suggestion(make_user, make_item, sent):
    user = make_user()
    mid = db.queue_outbound(user["id"], "a suggestion")
    db.q("UPDATE messages SET meta = %s WHERE id = %s", (db.J({"proactive": True, "item_id": make_item(user)}), mid))
    db.q("UPDATE users SET settings = '{\"paused\": true}' WHERE id = %s", (user["id"],))
    dispatch.run_once()
    sent.assert_not_called()
    assert status(mid) == "cancelled"
