import base64
from unittest.mock import patch

from tasteserver import db, storage
from tasteserver.config import MAX_BODY_BYTES

from .conftest import OTHER, PHONE, bearer


def test_oversized_bodies_rejected_with_or_without_a_length(sent, client):
    too_big = b"x" * (MAX_BODY_BYTES + 1)
    assert client.post("/v1/inbound", content=too_big).status_code == 413
    chunked = iter([too_big[:4_000_000], too_big[4_000_000:]])
    assert client.post("/v1/inbound", content=chunked).status_code == 413
    assert client.post("/v1/inbound", content=b"{}", headers={"Content-Length": "abc"}).status_code == 413


def test_transport_keys_cannot_read_user_data(make_user, client):
    headers = bearer(make_user()["id"], "transport")
    for path in ["/v1/me", "/v1/items", "/v1/profile", "/v1/messages", "/v1/me/memory"]:
        assert client.get(path, headers=headers).status_code == 403, path
    lowercase = {"Authorization": headers["Authorization"].replace("Bearer", "bearer")}
    assert client.get("/v1/outbound", headers=lowercase).status_code == 200


def test_list_bounds_and_admin_validation(make_user, client):
    user = make_user()
    admin = bearer(None, "admin")
    assert client.get(f"/v1/items?limit=-1&user_id={user['id']}", headers=admin).status_code == 422
    assert client.get(f"/v1/items?offset=-5&user_id={user['id']}", headers=admin).status_code == 422
    assert client.patch(f"/v1/admin/users/{user['id']}", headers=admin, json={"role": "root"}).status_code == 400
    assert client.patch(f"/v1/admin/users/{user['id']}", headers=admin, json={"tz": "Mars/Base"}).status_code == 400
    assert client.patch(f"/v1/admin/users/{user['id']}", headers=admin, json={"status": "disabled"}).status_code == 200


def test_relay_round_trip(make_user, client):
    user = make_user(transport="relay")
    headers = bearer(user["id"], "transport")
    hello = client.post("/v1/transport/hello", headers=headers, json={"handle": PHONE, "capabilities": ["react", "x"]})
    assert hello.json()["capabilities"] == ["react"]

    first = client.post("/v1/inbound", headers=headers, json={"handle": PHONE, "text": "hi", "external_id": "g1"})
    assert "job_id" in first.json()
    again = client.post("/v1/inbound", headers=headers, json={"handle": PHONE, "text": "hi", "external_id": "g1"})
    assert again.json()["duplicate"] is True
    assert client.post("/v1/inbound", headers=headers, json={"handle": OTHER, "text": "hi"}).status_code == 403

    mid = db.queue_outbound(user["id"], "hello back")
    queued = client.get("/v1/outbound", headers=headers).json()["messages"]
    assert [m["id"] for m in queued] == [mid]
    assert client.post(f"/v1/outbound/{mid}/ack", headers=headers, json={"external_id": "g2"}).status_code == 200
    assert db.q("SELECT status FROM messages WHERE id = %s", (mid,), one=True)["status"] == "sent"
    assert client.get("/v1/outbound", headers=headers).json()["messages"] == []


def test_relay_cannot_touch_another_users_messages(make_user, client):
    mine, theirs = make_user(transport="relay"), make_user(OTHER, transport="blooio")
    mid = db.queue_outbound(theirs["id"], "not yours")
    headers = bearer(mine["id"], "transport")
    assert client.post(f"/v1/outbound/{mid}/ack", headers=headers, json={}).status_code == 404
    assert client.get("/v1/outbound", headers=bearer(theirs["id"], "transport")).json()["messages"] == []


def test_relay_attachments_are_typed_and_validated(make_user, client):
    headers = bearer(make_user()["id"], "transport")
    bad = {"handle": PHONE, "attachments": [{"content_type": "image/png", "data_b64": "not base64!!"}]}
    assert client.post("/v1/inbound", headers=headers, json=bad).status_code == 400
    svg = {"content_type": "image/svg+xml", "data_b64": base64.b64encode(b"<svg onload=alert(1)>").decode()}
    png = {"content_type": "image/png", "data_b64": base64.b64encode(b"\x89PNG fake").decode()}
    with patch.object(storage, "put") as put:
        ok = client.post("/v1/inbound", headers=headers, json={"handle": PHONE, "attachments": [svg, png]})
    assert ok.status_code == 200
    assert [c.args[2] for c in put.call_args_list] == ["image/png"]
