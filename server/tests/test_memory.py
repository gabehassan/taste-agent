import json

import pytest
from fastapi import HTTPException

from tasteserver import db, memory, scheduler

from .conftest import OTHER


def test_memories_and_feedback_stay_with_their_owner(make_user, make_item):
    a, b = make_user(), make_user(OTHER)
    memory.remember(a["id"], "I love quiet interiors.")
    item = make_item(a)
    assert len(memory.memories(a["id"])) == 1
    assert memory.memories(b["id"]) == []
    with pytest.raises(HTTPException):
        memory.feedback(b["id"], item, "finished")
    memory.feedback(a["id"], item, "finished")
    memory.feedback(a["id"], item, "finished")
    assert len(db.q("SELECT * FROM item_events")) == 1
    assert memory.daily(a["id"], "2026-09-12")["picks"] == []
    assert memory.daily(a["id"], "2026-09-12")["finished_week"] == 1


def test_memory_holds_thirty_and_stays_valid_json(make_user):
    user = make_user()
    for i in range(30):
        memory.remember(user["id"], str(i) + "x" * 490)
    assert len(json.loads(memory.context(user["id"]))) == 30
    with pytest.raises(HTTPException):
        memory.remember(user["id"], "one too many")


def test_daily_picks_are_stable_and_respect_snoozes(make_user, make_item):
    user = make_user()
    for i in range(4):
        make_item(user, str(i))
    first = memory.daily(user["id"], "2026-09-12")["picks"]
    assert first == memory.daily(user["id"], "2026-09-12")["picks"]
    snoozed = first[0]["item"]["id"]
    memory.feedback(user["id"], snoozed, "later")
    assert snoozed not in [p["item"]["id"] for p in memory.daily(user["id"], "2026-09-12")["picks"]]
    assert snoozed not in [i["id"] for i in scheduler.proactive_candidates(user)]
