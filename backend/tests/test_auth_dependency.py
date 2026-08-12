"""Phase 8 tests: the get_current_user dependency.

Exercised through a real protected route so the whole chain is covered:
Authorization header -> HTTPBearer -> token decode -> user lookup.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_service import auth_service
from tests.conftest import FakeUsersCollection

client = TestClient(app)

ME = "/api/auth/me"
EMAIL = "user@example.com"
PASSWORD = "a-good-passphrase"


def register_and_login(users: FakeUsersCollection) -> tuple[str, str]:
    """Create an account and return (user_id, access_token)."""
    user = auth_service.register(EMAIL, PASSWORD)
    token = auth_service.authenticate(EMAIL, PASSWORD)
    return user.id, token.access_token


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Success ----------------------------------------------------------------


def test_valid_token_resolves_the_current_user(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    user_id, token = register_and_login(users)

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["id"] == user_id
    assert body["data"]["email"] == EMAIL


def test_response_carries_only_public_fields(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    _, token = register_and_login(users)

    data = client.get(ME, headers=bearer(token)).json()["data"]

    assert set(data.keys()) == {"id", "email", "created_at"}


# --- Missing or malformed credentials ---------------------------------------


def test_missing_authorization_header_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "TOKEN_MISSING"


@pytest.mark.parametrize(
    "header",
    ["Basic dXNlcjpwYXNz", "Token abc123", "bearerabc", "Digest xyz"],
    ids=["basic", "token", "no-space", "digest"],
)
def test_wrong_authorization_scheme_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, header: str
) -> None:
    response = client.get(ME, headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json()["error"]["code"] in {"TOKEN_INVALID", "TOKEN_MISSING"}


@pytest.mark.parametrize("value", ["Bearer", "Bearer ", "Bearer    "])
def test_empty_bearer_token_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, value: str
) -> None:
    response = client.get(ME, headers={"Authorization": value})

    assert response.status_code == 401
    assert response.json()["success"] is False


@pytest.mark.parametrize(
    "token", ["not.a.jwt", "abcdef", "a.b.c.d", "eyJhbGciOiJIUzI1NiJ9.x.y"]
)
def test_malformed_token_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, token: str
) -> None:
    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


# --- Invalid or expired tokens ----------------------------------------------


def test_expired_token_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    user_id, _ = register_and_login(users)
    past = datetime.now(UTC) - timedelta(days=1)
    expired = jwt.encode(
        {"sub": user_id, "iat": past, "exp": past + timedelta(minutes=5), "type": "access"},
        jwt_secret,
        algorithm="HS256",
    )

    response = client.get(ME, headers=bearer(expired))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_token_signed_with_another_secret_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    """The core forgery case: right shape, wrong key."""
    user_id, _ = register_and_login(users)
    forged = jwt.encode(
        {
            "sub": user_id,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        "attacker-chosen-secret-value-long-enough",
        algorithm="HS256",
    )

    response = client.get(ME, headers=bearer(forged))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_token_with_a_malformed_subject_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    bad_subject = jwt.encode(
        {
            "sub": "not-an-objectid",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        jwt_secret,
        algorithm="HS256",
    )

    response = client.get(ME, headers=bearer(bad_subject))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_token_for_a_deleted_user_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    """A valid signature is not enough — the account must still exist."""
    _, token = register_and_login(users)
    users.documents.clear()

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


def test_token_for_a_never_existing_user_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    orphan = jwt.encode(
        {
            "sub": str(ObjectId()),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        jwt_secret,
        algorithm="HS256",
    )

    response = client.get(ME, headers=bearer(orphan))

    assert response.status_code == 401


# --- Failure responses stay clean -------------------------------------------


def test_every_failure_uses_the_standard_error_envelope(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    for headers in ({}, bearer("garbage"), {"Authorization": "Basic abc"}):
        body = client.get(ME, headers=headers).json()

        assert set(body.keys()) == {"success", "message", "error"}
        assert body["success"] is False
        assert set(body["error"].keys()) == {"code", "details"}


def test_failures_never_leak_decoding_internals(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    raw = client.get(ME, headers=bearer("garbage.token.here")).text

    for leak in ("Traceback", "jwt.", "PyJWT", "site-packages", jwt_secret):
        assert leak not in raw


def test_database_outage_does_not_authenticate(
    failing_users: FakeUsersCollection, jwt_secret: str
) -> None:
    """Fail closed: no token may be honoured when the user cannot be checked."""
    token = jwt.encode(
        {
            "sub": str(ObjectId()),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        jwt_secret,
        algorithm="HS256",
    )

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_missing_jwt_secret_reports_configuration_error(
    users: FakeUsersCollection, no_jwt_secret: None
) -> None:
    response = client.get(ME, headers=bearer("any.token.value"))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
