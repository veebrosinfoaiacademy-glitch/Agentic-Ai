"""Phase 12 tests: quota enforcement on AI endpoints.

The important assertions here are about ordering and accounting:

* an anonymous request is refused before any counter or provider is touched;
* a malformed request does not burn quota, even though FastAPI runs the
  dependency before it validates the body;
* a rejected request never reaches Groq.
"""

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FakeCollection, FakeUsersCollection

client = TestClient(app)

CODE = "def add(a, b):\n    return a + b\n"
SOURCE = "Acme Corp released Widget 3 in March 2024."

# Every endpoint that spends provider budget, with a body that would succeed.
AI_ENDPOINTS = [
    ("/api/ai/test", {"prompt": "hello"}),
    ("/api/content/generate", {"topic": "AI in education"}),
    ("/api/content/summarize", {"text": SOURCE, "summary_type": "short"}),
    ("/api/content/rewrite", {"text": SOURCE, "instructions": "Clearer."}),
    ("/api/content/tone", {"text": SOURCE, "tone": "casual"}),
    ("/api/content/audience", {"text": SOURCE, "audience": "beginner"}),
    ("/api/content/format", {"text": SOURCE, "format": "bullet_points"}),
    ("/api/content/extract", {"text": SOURCE}),
    ("/api/developer/generate", {"language": "python", "description": "Add numbers"}),
    ("/api/developer/explain", {"language": "python", "code": CODE}),
    ("/api/developer/review", {"language": "python", "code": CODE}),
    ("/api/developer/refactor", {"language": "python", "code": CODE}),
    ("/api/developer/tests", {"language": "python", "code": CODE}),
    ("/api/developer/debug", {"language": "python", "code": CODE}),
    ("/api/developer/document", {"language": "python", "code": CODE}),
]
AI_IDS = [path.replace("/api/", "") for path, _ in AI_ENDPOINTS]


def sign_up(email: str) -> str:
    from app.services.auth_service import auth_service

    auth_service.register(email, "quota-tests-passphrase")
    return auth_service.authenticate(email, "quota-tests-passphrase").access_token


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def total(counters: FakeCollection, window: str = "hour") -> int:
    return sum(d["count"] for d in counters.documents if d["window"] == window)


# --- Enforced on every AI endpoint ------------------------------------------


@pytest.mark.parametrize(("endpoint", "payload"), AI_ENDPOINTS, ids=AI_IDS)
def test_every_ai_endpoint_counts_against_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
    endpoint: str,
    payload: dict,
) -> None:
    ai_limits(hour=10, day=50)
    recorded_generate.content = '{"summary": "ok", "content": "ok"}'
    token = sign_up("counted@example.com")

    response = client.post(endpoint, json=payload, headers=auth(token))

    assert response.status_code == 200, response.text
    assert total(usage_counters) == 1


def test_conversation_messages_count_against_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
) -> None:
    ai_limits(hour=10, day=50)
    token = sign_up("convo@example.com")
    conversation_id = client.post(
        "/api/conversations",
        json={"title": "Notes", "agent_type": "content"},
        headers=auth(token),
    ).json()["data"]["id"]
    assert total(usage_counters) == 0  # creating a conversation is free

    client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"task_type": "summarize", "prompt": SOURCE},
        headers=auth(token),
    )

    assert total(usage_counters) == 1


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/health", None),
        ("get", "/api/documents/supported-types", None),
        ("get", "/api/usage", None),
        ("get", "/api/auth/me", None),
        ("get", "/api/conversations", None),
    ],
    ids=["health", "supported-types", "usage", "me", "list-conversations"],
)
def test_non_ai_endpoints_do_not_consume_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    conversations: FakeCollection,
    method: str,
    path: str,
    payload,
) -> None:
    """Only provider spend is metered."""
    ai_limits(hour=10, day=50)
    token = sign_up(f"free{len(path)}@example.com")

    getattr(client, method)(path, headers=auth(token))

    assert usage_counters.documents == []


def test_document_upload_does_not_consume_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    documents: FakeCollection,
) -> None:
    """Uploading costs CPU and storage, not provider budget."""
    ai_limits(hour=10, day=50)
    token = sign_up("uploader@example.com")

    response = client.post(
        "/api/documents/upload",
        files={"file": ("a.txt", b"hello there", "text/plain")},
        headers=auth(token),
    )

    assert response.status_code == 201
    assert usage_counters.documents == []


# --- Over the limit ---------------------------------------------------------


def test_requests_are_refused_once_the_limit_is_reached(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=2, day=50)
    token = sign_up("limited@example.com")
    body = {"text": SOURCE, "summary_type": "short"}

    statuses = [
        client.post("/api/content/summarize", json=body, headers=auth(token)).status_code
        for _ in range(3)
    ]

    assert statuses == [200, 200, 429]


def test_the_refusal_uses_the_standard_error_envelope(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=1, day=50)
    token = sign_up("envelope@example.com")
    body = {"text": SOURCE, "summary_type": "short"}
    client.post("/api/content/summarize", json=body, headers=auth(token))

    response = client.post("/api/content/summarize", json=body, headers=auth(token))

    assert response.status_code == 429
    payload = response.json()
    assert set(payload.keys()) == {"success", "message", "error"}
    assert payload["success"] is False
    assert payload["error"]["code"] == "USAGE_LIMIT_EXCEEDED"
    assert payload["error"]["details"]["window"] == "hour"
    assert payload["error"]["details"]["limit"] == 1


def test_the_refusal_carries_retry_after(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=1, day=50)
    token = sign_up("retry@example.com")
    body = {"text": SOURCE, "summary_type": "short"}
    client.post("/api/content/summarize", json=body, headers=auth(token))

    response = client.post("/api/content/summarize", json=body, headers=auth(token))

    retry_after = response.json()["error"]["details"]["retry_after_seconds"]
    assert 0 < retry_after <= 3600
    assert response.headers.get("Retry-After") == str(retry_after)


def test_a_refused_request_never_reaches_the_provider(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    """The entire point of the quota: no spend past the limit."""
    ai_limits(hour=1, day=50)
    token = sign_up("noprovider@example.com")
    body = {"text": SOURCE, "summary_type": "short"}
    client.post("/api/content/summarize", json=body, headers=auth(token))
    calls_before = len(recorded_generate.calls)

    client.post("/api/content/summarize", json=body, headers=auth(token))

    assert len(recorded_generate.calls) == calls_before


def test_one_users_limit_does_not_affect_another(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=1, day=50)
    token_a = sign_up("first@example.com")
    token_b = sign_up("second@example.com")
    body = {"text": SOURCE, "summary_type": "short"}

    client.post("/api/content/summarize", json=body, headers=auth(token_a))

    assert client.post("/api/content/summarize", json=body, headers=auth(token_a)).status_code == 429
    assert client.post("/api/content/summarize", json=body, headers=auth(token_b)).status_code == 200


# --- Malformed requests must not burn quota ---------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "", "summary_type": "short"},
        {"summary_type": "short"},
        {"text": SOURCE, "summary_type": "invented"},
        {"text": "x" * 20_001, "summary_type": "short"},
    ],
    ids=["empty-text", "missing-text", "bad-enum", "oversized"],
)
def test_an_invalid_request_does_not_consume_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
    payload: dict,
) -> None:
    """FastAPI runs the dependency before validating the body, so the claim is
    taken and then refunded. The net effect must be zero."""
    ai_limits(hour=10, day=50)
    token = sign_up(f"invalid{abs(hash(str(payload))) % 9999}@example.com")

    response = client.post("/api/content/summarize", json=payload, headers=auth(token))

    assert response.status_code == 422
    assert total(usage_counters) == 0
    assert recorded_generate.calls == []


def test_repeated_invalid_requests_never_exhaust_the_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=2, day=50)
    token = sign_up("spammer@example.com")

    for _ in range(10):
        client.post("/api/content/summarize", json={"text": ""}, headers=auth(token))

    # Quota is untouched, so valid work still succeeds.
    response = client.post(
        "/api/content/summarize",
        json={"text": SOURCE, "summary_type": "short"},
        headers=auth(token),
    )
    assert response.status_code == 200
    assert total(usage_counters) == 1


def test_a_provider_failure_does_not_consume_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    failing_generate,
) -> None:
    """The user paid for work they never received."""
    ai_limits(hour=10, day=50)
    token = sign_up("providerfail@example.com")

    response = client.post(
        "/api/content/summarize",
        json={"text": SOURCE, "summary_type": "short"},
        headers=auth(token),
    )

    assert response.status_code == 502
    assert total(usage_counters) == 0


def test_a_successful_request_keeps_its_claim(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    """Valid AI work cannot bypass the quota."""
    ai_limits(hour=10, day=50)
    token = sign_up("kept@example.com")

    for _ in range(3):
        client.post(
            "/api/content/summarize",
            json={"text": SOURCE, "summary_type": "short"},
            headers=auth(token),
        )

    assert total(usage_counters) == 3


# --- Anonymous requests -----------------------------------------------------


@pytest.mark.parametrize(("endpoint", "payload"), AI_ENDPOINTS, ids=AI_IDS)
def test_anonymous_requests_are_refused_before_the_counter(
    usage_counters: FakeCollection, ai_limits, recorded_generate,
    endpoint: str, payload: dict,
) -> None:
    """Authentication resolves first, so no counter and no provider is reached."""
    ai_limits(hour=10, day=50)

    response = client.post(endpoint, json=payload)

    assert response.status_code == 401
    assert usage_counters.documents == []
    assert recorded_generate.calls == []


def test_an_invalid_token_is_refused_before_the_counter(
    jwt_secret: str, usage_counters: FakeCollection, ai_limits, recorded_generate
) -> None:
    ai_limits(hour=10, day=50)

    response = client.post(
        "/api/content/summarize",
        json={"text": SOURCE, "summary_type": "short"},
        headers=auth("not.a.real.jwt"),
    )

    assert response.status_code == 401
    assert usage_counters.documents == []


# --- Identity is never client-supplied --------------------------------------


def test_a_client_supplied_user_id_cannot_shift_the_quota(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    """The claim lands on the token's owner, whatever the body claims."""
    from app.services.auth_service import auth_service

    ai_limits(hour=10, day=50)
    token = sign_up("realuser@example.com")
    victim = auth_service.register("victim@example.com", "victim-passphrase-x")

    client.post(
        "/api/content/summarize",
        json={
            "text": SOURCE,
            "summary_type": "short",
            "user_id": victim.id,
            "owner_id": victim.id,
        },
        headers=auth(token),
    )

    charged = {str(d["user_id"]) for d in usage_counters.documents}
    assert victim.id not in charged
    assert len(charged) == 1


# --- Failing open -----------------------------------------------------------


def test_an_unreachable_counter_does_not_break_ai_requests(
    users: FakeUsersCollection,
    jwt_secret: str,
    failing_usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    """A counter outage must not become a service outage."""
    ai_limits(hour=1, day=1)
    token = sign_up("failopen@example.com")
    body = {"text": SOURCE, "summary_type": "short"}

    statuses = [
        client.post("/api/content/summarize", json=body, headers=auth(token)).status_code
        for _ in range(3)
    ]

    assert statuses == [200, 200, 200]


def test_a_counter_outage_never_leaks_database_detail(
    users: FakeUsersCollection,
    jwt_secret: str,
    failing_usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=1, day=1)
    token = sign_up("nodetail@example.com")

    response = client.post(
        "/api/content/summarize",
        json={"text": SOURCE, "summary_type": "short"},
        headers=auth(token),
    )

    for leak in ("pymongo", "ServerSelection", "mongodb", "Traceback"):
        assert leak.lower() not in response.text.lower()


def test_limits_disabled_allows_unlimited_requests(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=0, day=0)
    token = sign_up("unlimited@example.com")
    body = {"text": SOURCE, "summary_type": "short"}

    statuses = [
        client.post("/api/content/summarize", json=body, headers=auth(token)).status_code
        for _ in range(6)
    ]

    assert statuses == [200] * 6
    assert usage_counters.documents == []


# --- The usage endpoint -----------------------------------------------------


def test_usage_endpoint_requires_authentication() -> None:
    response = client.get("/api/usage")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_MISSING"


def test_usage_endpoint_reports_the_callers_own_counts(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=10, day=50)
    token = sign_up("reporter@example.com")
    for _ in range(2):
        client.post(
            "/api/content/summarize",
            json={"text": SOURCE, "summary_type": "short"},
            headers=auth(token),
        )

    data = client.get("/api/usage", headers=auth(token)).json()["data"]

    assert data["hour"]["used"] == 2
    assert data["hour"]["limit"] == 10
    assert data["hour"]["remaining"] == 8
    assert data["day"]["used"] == 2
    assert data["limited"] is True


def test_users_cannot_see_each_others_usage(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=10, day=50)
    token_a = sign_up("usagea@example.com")
    token_b = sign_up("usageb@example.com")
    for _ in range(3):
        client.post(
            "/api/content/summarize",
            json={"text": SOURCE, "summary_type": "short"},
            headers=auth(token_a),
        )

    data_b = client.get("/api/usage", headers=auth(token_b)).json()["data"]

    assert data_b["hour"]["used"] == 0


def test_usage_can_still_be_read_after_the_limit_is_reached(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    """Checking your balance must not itself require balance."""
    ai_limits(hour=1, day=50)
    token = sign_up("exhausted@example.com")
    body = {"text": SOURCE, "summary_type": "short"}
    client.post("/api/content/summarize", json=body, headers=auth(token))
    assert client.post("/api/content/summarize", json=body, headers=auth(token)).status_code == 429

    response = client.get("/api/usage", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["data"]["hour"]["remaining"] == 0


def test_usage_response_exposes_no_database_internals(
    users: FakeUsersCollection,
    jwt_secret: str,
    usage_counters: FakeCollection,
    ai_limits,
    recorded_generate,
) -> None:
    ai_limits(hour=10, day=50)
    token = sign_up("clean@example.com")
    client.post(
        "/api/content/summarize",
        json={"text": SOURCE, "summary_type": "short"},
        headers=auth(token),
    )

    raw = client.get("/api/usage", headers=auth(token)).text

    for internal in ("_id", "user_id", "window_start", "updated_at", "ObjectId"):
        assert internal not in raw


def test_usage_endpoint_is_documented_and_protected() -> None:
    spec = client.get("/openapi.json").json()

    operation = spec["paths"]["/api/usage"]["get"]
    assert operation["summary"]
    assert "security" in operation
