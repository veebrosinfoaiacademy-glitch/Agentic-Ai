"""Phase 8 tests: registration, login and user lookup.

Uses an in-memory users collection. No MongoDB Atlas account required.
"""

import pytest
from bson import ObjectId

from app.services.auth_service import auth_service
from app.utils.errors import AppError
from app.utils.security import decode_access_token, verify_password
from tests.conftest import FakeUsersCollection

EMAIL = "user@example.com"
PASSWORD = "a-good-passphrase"


# --- Registration -----------------------------------------------------------


def test_register_creates_a_user(users: FakeUsersCollection, jwt_secret: str) -> None:
    user = auth_service.register(EMAIL, PASSWORD)

    assert user.email == EMAIL
    assert ObjectId.is_valid(user.id)
    assert user.created_at is not None
    assert len(users.documents) == 1


def test_registration_stores_a_hash_and_never_the_password(
    users: FakeUsersCollection,
) -> None:
    """The single most important assertion in this phase."""
    auth_service.register(EMAIL, PASSWORD)

    stored = users.documents[0]
    assert "password" not in stored
    assert "password_hash" in stored
    assert stored["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in str(stored)
    assert verify_password(PASSWORD, stored["password_hash"]) is True


def test_registration_stores_timestamps(users: FakeUsersCollection) -> None:
    auth_service.register(EMAIL, PASSWORD)

    stored = users.documents[0]
    assert stored["created_at"] is not None
    assert stored["updated_at"] is not None


def test_registration_never_stores_a_token(users: FakeUsersCollection) -> None:
    """Tokens are stateless — nothing about them belongs in the database."""
    auth_service.register(EMAIL, PASSWORD)

    stored = str(users.documents[0])
    for forbidden in ("access_token", "token", "jwt", "bearer"):
        assert forbidden not in stored.lower()


def test_duplicate_email_is_rejected(users: FakeUsersCollection) -> None:
    auth_service.register(EMAIL, PASSWORD)

    with pytest.raises(AppError) as exc_info:
        auth_service.register(EMAIL, "another-passphrase")

    assert exc_info.value.code == "USER_ALREADY_EXISTS"
    assert exc_info.value.status_code == 409
    assert len(users.documents) == 1


def test_duplicate_detection_relies_on_the_unique_index(
    users: FakeUsersCollection,
) -> None:
    """The service does not read-then-write, which would race.

    The fake rejects at insert time, exactly as the unique index does, and
    registration still reports the right error — proving the service handles
    DuplicateKeyError rather than pre-checking.
    """
    auth_service.register(EMAIL, PASSWORD)

    with pytest.raises(AppError) as exc_info:
        auth_service.register(EMAIL, PASSWORD)

    assert exc_info.value.code == "USER_ALREADY_EXISTS"


def test_registration_reports_a_database_outage(
    failing_users: FakeUsersCollection,
) -> None:
    with pytest.raises(AppError) as exc_info:
        auth_service.register(EMAIL, PASSWORD)

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"
    assert exc_info.value.status_code == 503


# --- Authentication ---------------------------------------------------------


def test_login_with_correct_credentials_issues_a_token(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    user = auth_service.register(EMAIL, PASSWORD)

    token = auth_service.authenticate(EMAIL, PASSWORD)

    assert token.token_type == "bearer"
    assert token.expires_in > 0
    assert decode_access_token(token.access_token)["sub"] == user.id


def test_wrong_password_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    auth_service.register(EMAIL, PASSWORD)

    with pytest.raises(AppError) as exc_info:
        auth_service.authenticate(EMAIL, "wrong-passphrase")

    assert exc_info.value.code == "AUTHENTICATION_FAILED"
    assert exc_info.value.status_code == 401


def test_unknown_email_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    with pytest.raises(AppError) as exc_info:
        auth_service.authenticate("nobody@example.com", PASSWORD)

    assert exc_info.value.code == "AUTHENTICATION_FAILED"


def test_unknown_email_and_wrong_password_are_indistinguishable(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    """Account enumeration defence: identical code, status and message."""
    auth_service.register(EMAIL, PASSWORD)

    with pytest.raises(AppError) as wrong_password:
        auth_service.authenticate(EMAIL, "wrong-passphrase")
    with pytest.raises(AppError) as unknown_email:
        auth_service.authenticate("nobody@example.com", PASSWORD)

    assert wrong_password.value.code == unknown_email.value.code
    assert wrong_password.value.message == unknown_email.value.message
    assert wrong_password.value.status_code == unknown_email.value.status_code


def test_failure_message_names_neither_field(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    with pytest.raises(AppError) as exc_info:
        auth_service.authenticate("nobody@example.com", PASSWORD)

    message = exc_info.value.message.lower()
    assert "not found" not in message
    assert "incorrect password" not in message
    assert message == "invalid email or password"


def test_login_reports_a_database_outage_instead_of_authenticating(
    failing_users: FakeUsersCollection, jwt_secret: str
) -> None:
    """Authentication must fail closed when the database cannot be consulted."""
    with pytest.raises(AppError) as exc_info:
        auth_service.authenticate(EMAIL, PASSWORD)

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"
    assert exc_info.value.status_code == 503


def test_login_without_a_signing_secret_fails_cleanly(
    users: FakeUsersCollection, no_jwt_secret: None
) -> None:
    auth_service.register(EMAIL, PASSWORD)

    with pytest.raises(AppError) as exc_info:
        auth_service.authenticate(EMAIL, PASSWORD)

    assert exc_info.value.code == "AUTH_NOT_CONFIGURED"


# --- User lookup ------------------------------------------------------------


def test_lookup_returns_public_fields_only(users: FakeUsersCollection) -> None:
    registered = auth_service.register(EMAIL, PASSWORD)

    user = auth_service.get_user_by_id(registered.id)

    assert user.id == registered.id
    assert user.email == EMAIL
    assert not hasattr(user, "password_hash")
    assert "password_hash" not in user.model_dump()


@pytest.mark.parametrize(
    "bad_id",
    ["not-an-objectid", "", "12345", "z" * 24, None, "507f1f77bcf86cd79943901"],
    ids=["prose", "empty", "short", "non-hex", "none", "truncated"],
)
def test_malformed_user_id_is_an_auth_error_not_a_crash(
    users: FakeUsersCollection, bad_id
) -> None:
    """A bad ObjectId must never surface as a raw PyMongo exception."""
    with pytest.raises(AppError) as exc_info:
        auth_service.get_user_by_id(bad_id)

    assert exc_info.value.code == "TOKEN_INVALID"
    assert exc_info.value.status_code == 401


def test_deleted_user_is_rejected(users: FakeUsersCollection) -> None:
    """A token can outlive the account it names."""
    registered = auth_service.register(EMAIL, PASSWORD)
    users.documents.clear()

    with pytest.raises(AppError) as exc_info:
        auth_service.get_user_by_id(registered.id)

    assert exc_info.value.code == "USER_NOT_FOUND"
    assert exc_info.value.status_code == 401


def test_lookup_reports_a_database_outage(failing_users: FakeUsersCollection) -> None:
    with pytest.raises(AppError) as exc_info:
        auth_service.get_user_by_id(str(ObjectId()))

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"


# --- Logging hygiene --------------------------------------------------------


def test_nothing_sensitive_is_logged(
    users: FakeUsersCollection, jwt_secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        auth_service.register(EMAIL, PASSWORD)
        auth_service.authenticate(EMAIL, PASSWORD)
        try:
            auth_service.authenticate(EMAIL, "wrong-passphrase")
        except AppError:
            pass

    logged = caplog.text
    assert PASSWORD not in logged
    assert "wrong-passphrase" not in logged
    assert "$argon2id$" not in logged
    assert jwt_secret not in logged
