"""Phase 11 tests: the /api/conversations HTTP contract.

Includes the cross-user attack matrix — User B attempting every operation on
User A's conversation, through real tokens and the real auth dependency.
"""

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.conversation_schemas import MAX_PAGE_SIZE, MAX_TITLE_CHARS
from tests.conftest import FakeCollection, FakeUsersCollection

client = TestClient(app)

BASE = "/api/conversations"


def sign_up(email: str) -> str:
    """Register an account and return a real signed token."""
    from app.services.auth_service import auth_service

    auth_service.register(email, "conversation-tests-passphrase")
    return auth_service.authenticate(email, "conversation-tests-passphrase").access_token


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create(token: str, title: str = "My conversation", agent: str = "content") -> str:
    response = client.post(
        BASE, json={"title": title, "agent_type": agent}, headers=auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


# --- Authentication ---------------------------------------------------------


def test_every_conversation_route_requires_a_token() -> None:
    conversation_id = str(ObjectId())
    anonymous = [
        ("post", BASE, {"title": "x", "agent_type": "content"}),
        ("get", BASE, None),
        ("get", f"{BASE}/{conversation_id}", None),
        ("patch", f"{BASE}/{conversation_id}", {"title": "x"}),
        ("delete", f"{BASE}/{conversation_id}", None),
        ("post", f"{BASE}/{conversation_id}/messages", {"task_type": "summarize", "prompt": "x"}),
    ]

    for method, path, payload in anonymous:
        response = getattr(client, method)(path, **({"json": payload} if payload else {}))
        assert response.status_code == 401, f"{method.upper()} {path}"
        assert response.json()["error"]["code"] == "TOKEN_MISSING"


def test_invalid_token_is_rejected(jwt_secret: str) -> None:
    response = client.get(BASE, headers=auth("not.a.real.jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_anonymous_message_never_reaches_the_provider(recorded_generate) -> None:
    client.post(
        f"{BASE}/{ObjectId()}/messages",
        json={"task_type": "summarize", "prompt": "x"},
    )

    assert recorded_generate.calls == []


# --- CRUD -------------------------------------------------------------------


def test_create_returns_the_standard_envelope(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    token = sign_up("creator@example.com")

    response = client.post(
        BASE, json={"title": "  Python Review  ", "agent_type": "developer"},
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"success", "message", "data"}
    data = body["data"]
    assert data["title"] == "Python Review"  # trimmed
    assert data["agent_type"] == "developer"
    assert set(data.keys()) == {
        "id", "title", "agent_type", "created_at", "updated_at", "message_count",
    }


def test_list_returns_a_page(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    token = sign_up("lister@example.com")
    for index in range(3):
        create(token, f"Conversation {index}")

    body = client.get(BASE, headers=auth(token)).json()["data"]

    assert body["total"] == 3
    assert body["page"] == 1
    assert len(body["conversations"]) == 3
    assert body["has_more"] is False


def test_get_returns_the_transcript(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
) -> None:
    recorded_generate.content = "A summary."
    token = sign_up("reader@example.com")
    conversation_id = create(token)
    client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"task_type": "summarize", "prompt": "Long text."},
        headers=auth(token),
    )

    data = client.get(f"{BASE}/{conversation_id}", headers=auth(token)).json()["data"]

    assert data["message_count"] == 2
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][1]["content"] == "A summary."


def test_rename_updates_the_title(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    token = sign_up("renamer@example.com")
    conversation_id = create(token, "Old title")

    response = client.patch(
        f"{BASE}/{conversation_id}", json={"title": "New title"}, headers=auth(token)
    )

    assert response.status_code == 200
    assert response.json()["data"]["title"] == "New title"


def test_delete_removes_the_conversation(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
) -> None:
    token = sign_up("deleter@example.com")
    conversation_id = create(token)

    response = client.delete(f"{BASE}/{conversation_id}", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert client.get(f"{BASE}/{conversation_id}", headers=auth(token)).status_code == 404


# --- Cross-user attack matrix -----------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("get", "", None),
        ("patch", "", {"title": "hijacked"}),
        ("delete", "", None),
        ("post", "/messages", {"task_type": "summarize", "prompt": "intrusion"}),
    ],
    ids=["read", "rename", "delete", "send-message"],
)
def test_user_b_cannot_touch_user_a_conversation(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
    method: str,
    suffix: str,
    payload,
) -> None:
    token_a = sign_up("owner@example.com")
    token_b = sign_up("attacker@example.com")
    conversation_id = create(token_a, "User A's private notes")

    response = getattr(client, method)(
        f"{BASE}/{conversation_id}{suffix}",
        headers=auth(token_b),
        **({"json": payload} if payload else {}),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    # Nothing leaked, nothing changed, no provider spend.
    assert "User A's private notes" not in response.text
    assert conversations.documents[0]["title"] == "User A's private notes"
    assert recorded_generate.calls == []


def test_list_never_includes_another_users_conversations(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    token_a = sign_up("a@example.com")
    token_b = sign_up("b@example.com")
    create(token_a, "A private")
    create(token_b, "B private")

    body_a = client.get(BASE, headers=auth(token_a)).json()["data"]
    body_b = client.get(BASE, headers=auth(token_b)).json()["data"]

    assert [c["title"] for c in body_a["conversations"]] == ["A private"]
    assert [c["title"] for c in body_b["conversations"]] == ["B private"]


def test_a_foreign_conversation_looks_exactly_like_a_missing_one(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection,
    messages: FakeCollection,
) -> None:
    token_a = sign_up("owner2@example.com")
    token_b = sign_up("attacker2@example.com")
    owned_by_a = create(token_a)

    foreign = client.get(f"{BASE}/{owned_by_a}", headers=auth(token_b))
    missing = client.get(f"{BASE}/{ObjectId()}", headers=auth(token_b))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


# --- Identity cannot be supplied by the client ------------------------------


def test_a_user_id_in_the_body_is_ignored(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    from app.services.auth_service import auth_service

    token_a = sign_up("real@example.com")
    victim = auth_service.register("victim@example.com", "victim-passphrase-x")

    response = client.post(
        BASE,
        json={
            "title": "Impersonation attempt",
            "agent_type": "content",
            "user_id": victim.id,
            "owner_id": victim.id,
        },
        headers=auth(token_a),
    )

    assert response.status_code == 201
    # Stored against the token's owner, not the id in the body.
    assert conversations.documents[0]["user_id"] != ObjectId(victim.id)


def test_conversation_request_schemas_expose_no_identity_fields() -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    forbidden = {"user_id", "userId", "owner_id", "account_id", "sub"}
    offenders = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        if "Conversation" in name or "Message" in name
        for field in schema.get("properties", {})
        if field in forbidden
    ]

    assert offenders == []


def test_rename_cannot_change_protected_fields(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    token = sign_up("mutator@example.com")
    conversation_id = create(token, "Original", agent="content")
    before = dict(conversations.documents[0])

    client.patch(
        f"{BASE}/{conversation_id}",
        json={
            "title": "Renamed",
            "agent_type": "developer",
            "user_id": str(ObjectId()),
            "created_at": "1999-01-01T00:00:00Z",
        },
        headers=auth(token),
    )

    after = conversations.documents[0]
    assert after["title"] == "Renamed"
    assert after["agent_type"] == before["agent_type"]
    assert after["user_id"] == before["user_id"]
    assert after["created_at"] == before["created_at"]


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"agent_type": "content"},
        {"title": "", "agent_type": "content"},
        {"title": "   ", "agent_type": "content"},
        {"title": "x" * (MAX_TITLE_CHARS + 1), "agent_type": "content"},
        {"title": "ok", "agent_type": "marketing"},
        {"title": "ok"},
    ],
    ids=["empty", "no-title", "blank", "spaces", "too-long", "bad-agent", "no-agent"],
)
def test_invalid_create_requests_are_rejected(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection,
    payload: dict,
) -> None:
    token = sign_up(f"validator{abs(hash(str(payload))) % 9999}@example.com")

    response = client.post(BASE, json=payload, headers=auth(token))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "bad_id", ["not-an-objectid", "12345", "z" * 24], ids=["prose", "short", "non-hex"]
)
def test_malformed_conversation_id_returns_a_clean_error(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection,
    bad_id: str,
) -> None:
    token = sign_up(f"ids{len(bad_id)}@example.com")

    response = client.get(f"{BASE}/{bad_id}", headers=auth(token))

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_ID"
    for leak in ("Traceback", "bson", "pymongo", "ObjectId"):
        assert leak not in response.text


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": MAX_PAGE_SIZE + 1}],
    ids=["page-zero", "page-negative", "size-zero", "size-too-large"],
)
def test_invalid_pagination_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection,
    params: dict,
) -> None:
    token = sign_up(f"page{abs(hash(str(params))) % 9999}@example.com")

    response = client.get(BASE, params=params, headers=auth(token))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"task_type": "summarize"},
        {"prompt": "text"},
        {"task_type": "summarize", "prompt": ""},
        {"task_type": "summarize", "prompt": "   "},
        {"task_type": "invented_task", "prompt": "text"},
        {"task_type": "summarize", "prompt": "x" * 30_001},
    ],
    ids=["no-prompt", "no-task", "empty", "blank", "unknown-task", "too-long"],
)
def test_invalid_message_requests_are_rejected(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
    payload: dict,
) -> None:
    token = sign_up(f"msg{abs(hash(str(payload))) % 9999}@example.com")
    conversation_id = create(token)

    response = client.post(
        f"{BASE}/{conversation_id}/messages", json=payload, headers=auth(token)
    )

    assert response.status_code == 422
    assert recorded_generate.calls == []
    assert messages.documents == []


# --- Agent routing over HTTP ------------------------------------------------


def test_a_developer_task_in_a_content_conversation_is_rejected(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
) -> None:
    token = sign_up("router@example.com")
    conversation_id = create(token, agent="content")

    response = client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"task_type": "review", "prompt": "def f(): pass"},
        headers=auth(token),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "TASK_NOT_SUPPORTED"
    assert "content task" in body["message"]
    assert recorded_generate.calls == []


def test_provider_failure_returns_the_existing_error_envelope(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
    failing_generate,
) -> None:
    token = sign_up("failer@example.com")
    conversation_id = create(token)

    response = client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"task_type": "summarize", "prompt": "text"},
        headers=auth(token),
    )

    assert response.status_code == 502
    assert response.json() == {
        "success": False,
        "message": "AI service is temporarily unavailable",
        "error": {"code": "AI_PROVIDER_ERROR", "details": None},
    }
    # No fabricated reply was stored.
    assert [d["role"] for d in messages.documents] == ["user"]


# --- Database failures ------------------------------------------------------


def test_database_outage_returns_503(
    users: FakeUsersCollection, jwt_secret: str, failing_conversations: FakeCollection
) -> None:
    token = sign_up("outage@example.com")

    response = client.get(BASE, headers=auth(token))

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DATABASE_UNAVAILABLE"
    for leak in ("pymongo", "ServerSelection", "Traceback", "mongodb+srv"):
        assert leak.lower() not in response.text.lower()


# --- OpenAPI ----------------------------------------------------------------


def test_all_conversation_routes_are_documented_and_protected() -> None:
    spec = client.get("/openapi.json").json()

    expected = {
        ("post", BASE), ("get", BASE),
        ("get", f"{BASE}/{{conversation_id}}"),
        ("patch", f"{BASE}/{{conversation_id}}"),
        ("delete", f"{BASE}/{{conversation_id}}"),
        ("post", f"{BASE}/{{conversation_id}}/messages"),
    }

    for method, path in expected:
        operation = spec["paths"][path][method]
        assert operation["summary"], f"{method} {path} has no summary"
        assert "security" in operation, f"{method} {path} is not protected"


def test_responses_never_expose_the_owner_id(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
) -> None:
    token = sign_up("privacy@example.com")
    conversation_id = create(token)
    client.post(
        f"{BASE}/{conversation_id}/messages",
        json={"task_type": "summarize", "prompt": "text"},
        headers=auth(token),
    )

    for response in (
        client.get(BASE, headers=auth(token)),
        client.get(f"{BASE}/{conversation_id}", headers=auth(token)),
    ):
        assert "user_id" not in response.text
        assert "password" not in response.text.lower()
