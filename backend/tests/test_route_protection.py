"""Phase 10 tests: authorization on every protected endpoint.

Deliberately does NOT use the `authenticated` fixture — these tests exercise
the real `require_user` dependency, including real token decoding.

The important assertions here are not just "401 was returned". They are that
authentication happens BEFORE anything expensive: no Groq call, no document
extraction, no provider spend for an anonymous request.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FakeUsersCollection

client = TestClient(app)

CODE = "def add(a, b):\n    return a + b\n"
SOURCE = "Acme Corp released Widget 3 in March 2024."

# Every protected endpoint with a body that WOULD succeed if authenticated.
# Keeping the payloads valid matters: a 401 on an invalid body would prove
# nothing about ordering.
PROTECTED = [
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
PROTECTED_IDS = [path.replace("/api/", "") for path, _ in PROTECTED]

UPLOAD = "/api/documents/upload"
UPLOAD_FILE = {"file": ("notes.txt", b"Some document text.", "text/plain")}

PUBLIC = [
    ("get", "/api/health", None),
    ("get", "/api/documents/supported-types", None),
]


def register_and_login(users: FakeUsersCollection) -> str:
    """Create a real account and return a real signed token."""
    from app.services.auth_service import auth_service

    auth_service.register("owner@example.com", "route-protection-passphrase")
    return auth_service.authenticate("owner@example.com", "route-protection-passphrase").access_token


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def expired_token(secret: str, user_id: str) -> str:
    past = datetime.now(UTC) - timedelta(days=2)
    return jwt.encode(
        {"sub": user_id, "iat": past, "exp": past + timedelta(minutes=5), "type": "access"},
        secret,
        algorithm="HS256",
    )


def forged_token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        "an-attacker-chosen-secret-of-sufficient-length",
        algorithm="HS256",
    )


# --- The matrix: no token -> 401 --------------------------------------------


@pytest.mark.parametrize(("endpoint", "payload"), PROTECTED, ids=PROTECTED_IDS)
def test_anonymous_request_is_rejected(endpoint: str, payload: dict) -> None:
    response = client.post(endpoint, json=payload)

    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "TOKEN_MISSING"


def test_anonymous_upload_is_rejected() -> None:
    response = client.post(UPLOAD, files=UPLOAD_FILE)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_MISSING"


# --- The matrix: invalid / expired / forged token -> 401 --------------------


@pytest.mark.parametrize(("endpoint", "payload"), PROTECTED, ids=PROTECTED_IDS)
def test_malformed_token_is_rejected(
    jwt_secret: str, endpoint: str, payload: dict
) -> None:
    response = client.post(endpoint, json=payload, headers=bearer("not.a.real.jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_malformed_token_is_rejected_for_upload(jwt_secret: str) -> None:
    response = client.post(UPLOAD, files=UPLOAD_FILE, headers=bearer("not.a.real.jwt"))

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [PROTECTED[1], PROTECTED[9], PROTECTED[0]],
    ids=["content", "developer", "ai"],
)
def test_expired_token_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, endpoint: str, payload: dict
) -> None:
    token = expired_token(jwt_secret, str(ObjectId()))

    response = client.post(endpoint, json=payload, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [PROTECTED[1], PROTECTED[9], PROTECTED[0]],
    ids=["content", "developer", "ai"],
)
def test_forged_signature_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, endpoint: str, payload: dict
) -> None:
    """A structurally perfect token signed with the wrong key."""
    response = client.post(
        endpoint, json=payload, headers=bearer(forged_token(str(ObjectId())))
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.parametrize(
    ("endpoint", "payload"), [PROTECTED[1], PROTECTED[9]], ids=["content", "developer"]
)
def test_wrong_authorization_scheme_is_rejected(
    jwt_secret: str, endpoint: str, payload: dict
) -> None:
    response = client.post(
        endpoint, json=payload, headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )

    assert response.status_code == 401


def test_token_for_a_deleted_user_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, recorded_generate
) -> None:
    """A valid signature is not enough — the account must still exist."""
    token = register_and_login(users)
    users.documents.clear()

    response = client.post(
        "/api/content/summarize",
        json={"text": SOURCE, "summary_type": "short"},
        headers=bearer(token),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


# --- The matrix: valid token -> existing behaviour --------------------------


@pytest.mark.parametrize(("endpoint", "payload"), PROTECTED, ids=PROTECTED_IDS)
def test_valid_token_reaches_the_endpoint(
    users: FakeUsersCollection,
    jwt_secret: str,
    groq_configured: None,
    recorded_generate,
    endpoint: str,
    payload: dict,
) -> None:
    """With a real token, every endpoint behaves exactly as before Phase 10."""
    recorded_generate.content = '{"summary": "ok", "content": "ok"}'
    token = register_and_login(users)

    response = client.post(endpoint, json=payload, headers=bearer(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert set(body.keys()) == {"success", "message", "data"}


def test_valid_token_reaches_upload(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    token = register_and_login(users)

    response = client.post(UPLOAD, files=UPLOAD_FILE, headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["data"]["text"] == "Some document text."


# --- Public endpoints stay public -------------------------------------------


@pytest.mark.parametrize(("method", "path", "payload"), PUBLIC, ids=[p for _, p, _ in PUBLIC])
def test_public_endpoints_need_no_token(method: str, path: str, payload) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 200


def test_supported_types_exposes_only_global_configuration() -> None:
    """Kept public because it contains no user-specific data.

    It is server configuration the sign-in page could legitimately show;
    protecting it would add a token requirement for no privacy gain.
    """
    data = client.get("/api/documents/supported-types").json()["data"]

    assert set(data.keys()) == {
        "extensions", "max_file_size_mb", "max_extracted_characters", "ocr_supported",
    }


# --- Authentication happens BEFORE anything expensive -----------------------


@pytest.mark.parametrize(("endpoint", "payload"), PROTECTED, ids=PROTECTED_IDS)
def test_anonymous_request_never_reaches_the_ai_provider(
    recorded_generate, endpoint: str, payload: dict
) -> None:
    """The point of protecting these routes: no anonymous provider spend."""
    response = client.post(endpoint, json=payload)

    assert response.status_code == 401
    assert recorded_generate.calls == []


@pytest.mark.parametrize(
    "token_header",
    [None, {"Authorization": "Bearer garbage.token.here"}, {"Authorization": "Basic x"}],
    ids=["none", "malformed", "wrong-scheme"],
)
def test_bad_credentials_never_reach_the_ai_provider(
    jwt_secret: str, recorded_generate, token_header
) -> None:
    client.post(
        "/api/content/generate", json={"topic": "AI"}, headers=token_header or {}
    )

    assert recorded_generate.calls == []


def test_anonymous_upload_never_runs_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document parsing must not run for an unauthenticated caller."""
    calls = []

    async def spy(upload):
        calls.append(upload)
        raise AssertionError("extraction must not run for an anonymous request")

    monkeypatch.setattr(
        "app.routes.documents.document_service.process_upload", spy
    )

    response = client.post(UPLOAD, files=UPLOAD_FILE)

    assert response.status_code == 401
    assert calls == []


# --- Identity comes from the token, never from the client -------------------


def test_client_supplied_user_id_cannot_override_the_token(
    users: FakeUsersCollection, jwt_secret: str, recorded_generate
) -> None:
    """A user_id in the body is ignored — the JWT is the only identity."""
    from app.services.auth_service import auth_service

    attacker = auth_service.register("attacker@example.com", "attacker-passphrase-x")
    victim = auth_service.register("victim@example.com", "victim-passphrase-x")
    token = auth_service.authenticate(
        "attacker@example.com", "attacker-passphrase-x"
    ).access_token

    response = client.post(
        "/api/content/summarize",
        json={
            "text": SOURCE,
            "summary_type": "short",
            # All ignored: the request schema has no such fields, and identity
            # is never read from the body.
            "user_id": victim.id,
            "sub": victim.id,
            "email": "victim@example.com",
        },
        headers=bearer(token),
    )

    assert response.status_code == 200
    # The extra keys were dropped by Pydantic, never forwarded to the agent.
    prompt = recorded_generate.user_prompt
    assert victim.id not in prompt
    assert attacker.id not in prompt


def test_request_schemas_expose_no_user_id_field() -> None:
    """Structural guarantee: no protected endpoint accepts an identity field."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    forbidden = {"user_id", "userId", "owner_id", "sub", "account_id"}
    offenders = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        if name.endswith("Request")
        for field in schema.get("properties", {})
        if field in forbidden
    ]

    assert offenders == [], f"identity fields accepted from clients: {offenders}"


# --- OpenAPI advertises the requirement -------------------------------------


def test_every_agent_and_upload_route_declares_bearer_security() -> None:
    """Catches a future route added without protection.

    Cheaper than remembering, and it fails loudly in CI rather than shipping
    an open AI endpoint.
    """
    spec = client.get("/openapi.json").json()

    must_be_protected = [
        path
        for path in spec["paths"]
        if path.startswith(
            ("/api/content/", "/api/developer/", "/api/ai/", "/api/conversations")
        )
        or path == "/api/documents/upload"
    ]
    # 7 content + 7 developer + 1 ai + 1 upload + 3 conversation paths
    assert len(must_be_protected) == 19

    unprotected = [
        f"{method.upper()} {path}"
        for path in must_be_protected
        for method, op in spec["paths"][path].items()
        if "security" not in op
    ]
    assert unprotected == [], f"unprotected routes: {unprotected}"


def test_protected_routes_reference_the_bearer_scheme() -> None:
    spec = client.get("/openapi.json").json()

    security = spec["paths"]["/api/content/generate"]["post"]["security"]
    assert any("Bearer" in entry for entry in security)
    assert spec["components"]["securitySchemes"]["Bearer"]["scheme"] == "bearer"


def test_openapi_never_exposes_server_secrets(jwt_secret: str) -> None:
    from app.config import settings

    raw = client.get("/openapi.json").text

    assert jwt_secret not in raw
    assert "mongodb+srv" not in raw
    if settings.GROQ_API_KEY:
        assert settings.GROQ_API_KEY not in raw


# --- Logging hygiene --------------------------------------------------------


def test_authorised_requests_do_not_log_the_token(
    users: FakeUsersCollection,
    jwt_secret: str,
    recorded_generate,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The audit line names the user by id, never by credential."""
    token = register_and_login(users)

    with caplog.at_level("DEBUG"):
        client.post(
            "/api/content/summarize",
            json={"text": SOURCE, "summary_type": "short"},
            headers=bearer(token),
        )

    assert token not in caplog.text
    assert "Authorization" not in caplog.text
    assert jwt_secret not in caplog.text
    # But it does record who made the call.
    assert "Authorised POST /api/content/summarize" in caplog.text
