"""Shared fixtures. Tests that touch Postgres need TEST_DATABASE_URL; each run gets its own throwaway schema.
No test makes a model call or sends a real message."""

import os
import uuid
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused@localhost/unused")

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from tasteserver import api, auth, blooio, db, dispatch

PHONE = "+12025550143"
OTHER = "+12025550144"


@pytest.fixture(scope="session")
def pg():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run the Postgres tests")
    schema = "taste_test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        original = db.pool
        db.pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=6,
            open=True,
            kwargs={"row_factory": dict_row, "options": f"-c search_path={schema}"},
        )
        try:
            db.migrate()
            yield
        finally:
            db.pool.close()
            db.pool = original
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def sent(pg):
    """A clean database with Blooio stubbed out. Yields the mock standing in for blooio.send_text."""
    db.q("TRUNCATE users, api_keys, invites, webhook_events, rate_limits, audit_log, jobs CASCADE")
    db.set_setting("open_signup", False)
    reply = {"id": "sent_test", "chat_id": "chat_test", "status": "queued"}
    with (
        patch.object(blooio, "send_text", return_value=reply) as send_text,
        patch.object(blooio, "typing"),
        patch.object(blooio, "enabled", return_value=True),
        patch.object(blooio, "NUMBER", OTHER),
        patch.object(dispatch.time, "sleep"),
    ):
        yield send_text


@pytest.fixture
def make_user(sent):
    def make(phone=PHONE, transport="blooio"):
        user = db.q("INSERT INTO users(transport) VALUES (%s) RETURNING *", (transport,), one=True)
        db.q("INSERT INTO handles(user_id, address) VALUES (%s, %s)", (user["id"], phone))
        return user

    return make


@pytest.fixture
def make_item():
    def make(user, title="a quiet room"):
        return db.add_item(
            user["id"],
            title=title,
            kind="essay",
            summary="on space and attention",
            snippets=["A room can make room for a thought."],
            tags=["design"],
            read_minutes=5,
        )

    return make


@pytest.fixture
def client():
    return TestClient(api.app)


def bearer(user_id, *scopes):
    raw, _ = auth.create_key(user_id, "test", list(scopes))
    return {"Authorization": f"Bearer {raw}"}
