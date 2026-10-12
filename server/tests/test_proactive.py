import datetime as dt
from unittest.mock import patch

from tasteserver import brain, db, handlers, memory, scheduler

from .conftest import OTHER


def choice(**kw):
    return brain.ProactiveChoice(
        **{"send": True, "item_id": 0, "excerpt_index": 0, "connection": "", "reason": "", **kw}
    )


def test_silence_is_an_option_and_quotes_are_never_rewritten(make_user, make_item):
    user = make_user()
    item = make_item(user)
    with patch.object(brain, "proactive_choice", return_value=choice(send=False, reason="no concrete connection")):
        assert handlers.do_proactive(user) is None
    assert not db.q("SELECT * FROM messages")

    pick = choice(item_id=item, connection="this connects to your interest in interiors.", reason="explicit interest")
    with patch.object(brain, "proactive_choice", return_value=pick):
        mid = handlers.do_proactive(user)
    row = db.q("SELECT * FROM messages WHERE id = %s", (mid,), one=True)
    assert "A room can make room for a thought." in row["text"]
    assert f"/items/{item}" in row["text"]
    assert row["meta"]["proactive"] is True
    assert row["meta"]["item_id"] == item


def test_the_model_cannot_pick_another_users_item(make_user, make_item):
    a, b = make_user(), make_user(OTHER)
    make_item(a)
    other = make_item(b)
    with patch.object(brain, "proactive_choice", return_value=choice(item_id=other, connection="test")):
        assert handlers.do_proactive(a) is None
    assert not db.q("SELECT * FROM messages")


def test_two_unanswered_suggestions_wait_for_engagement(make_user, make_item):
    user = make_user()
    item = make_item(user)
    for _ in range(2):
        mid = db.queue_outbound(user["id"], "a suggestion")
        db.q("UPDATE messages SET meta = '{\"proactive\": true}', status = 'sent' WHERE id = %s", (mid,))
    assert not scheduler.attention_available(user)
    memory.feedback(user["id"], item, "later")
    assert scheduler.attention_available(user)


def test_due_slots_respect_quiet_hours(make_user):
    user = make_user()
    db.set_user_state(
        user["id"], plan={"date": "2026-09-12", "slots": [{"at": "2026-09-12T12:00:00-04:00", "done": False}]}
    )
    with patch.object(scheduler, "_now", return_value=dt.datetime.fromisoformat("2026-09-12T23:00:00-04:00")):
        assert scheduler.due_slot(user) is None
    with patch.object(scheduler, "_now", return_value=dt.datetime.fromisoformat("2026-09-12T14:00:00-04:00")):
        assert scheduler.due_slot(user) == 0
