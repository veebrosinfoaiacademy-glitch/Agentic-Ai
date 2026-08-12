"""Phase 8 tests: password hashing and JWT handling.

Entirely offline. No database, no real signing secret.
"""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings
from app.utils.errors import AppError
from app.utils.security import (
    TOKEN_TYPE,
    create_access_token,
    decode_access_token,
    hash_password,
    token_lifetime_seconds,
    verify_dummy_password,
    verify_password,
)

PASSWORD = "a-good-passphrase"
USER_ID = "507f1f77bcf86cd799439011"


# --- Password hashing -------------------------------------------------------


def test_hash_is_argon2id() -> None:
    """Argon2id specifically, not argon2i or argon2d."""
    assert hash_password(PASSWORD).startswith("$argon2id$")


def test_hash_never_contains_the_plaintext() -> None:
    assert PASSWORD not in hash_password(PASSWORD)


def test_hashing_is_salted() -> None:
    """Identical passwords must not produce identical hashes.

    Without a salt, equal hashes reveal that two accounts share a password.
    """
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_correct_password_verifies() -> None:
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


@pytest.mark.parametrize(
    "wrong",
    ["wrong-password", "a-good-passphras", "A-Good-Passphrase", "", " "],
    ids=["different", "truncated", "case", "empty", "space"],
)
def test_incorrect_password_fails(wrong: str) -> None:
    assert verify_password(wrong, hash_password(PASSWORD)) is False


@pytest.mark.parametrize(
    "bad_hash", ["", "not-a-hash", "$argon2id$broken", "$2b$12$oldbcrypthash"]
)
def test_unusable_stored_hash_fails_login_instead_of_crashing(bad_hash: str) -> None:
    """A corrupt hash must fail the login, not 500 the request."""
    assert verify_password(PASSWORD, bad_hash) is False


def test_long_password_is_accepted() -> None:
    """Argon2id has no 72-byte ceiling, unlike bcrypt which raises above it."""
    long_password = "x" * 200

    assert verify_password(long_password, hash_password(long_password)) is True


def test_unicode_password_round_trips() -> None:
    passphrase = "correct-horse-電池-café-🔐"

    assert verify_password(passphrase, hash_password(passphrase)) is True


def test_dummy_verification_always_fails_but_does_work() -> None:
    """Used on the no-such-user path so login timing does not leak."""
    start = time.perf_counter()
    result = verify_dummy_password(PASSWORD)
    elapsed = time.perf_counter() - start

    assert result is False
    # Real hashing work happened; a bare `return False` would be ~0s.
    assert elapsed > 0.0005


# --- Token creation ---------------------------------------------------------


def test_token_carries_only_minimal_claims(jwt_secret: str) -> None:
    token = create_access_token(USER_ID)

    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])

    assert set(payload.keys()) == {"sub", "iat", "exp", "type"}
    assert payload["sub"] == USER_ID
    assert payload["type"] == TOKEN_TYPE


def test_token_payload_contains_no_credentials(jwt_secret: str) -> None:
    """A JWT is signed, not encrypted — anyone holding it can read it."""
    token = create_access_token(USER_ID)

    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])

    for forbidden in ("password", "password_hash", "email", "hash", "secret"):
        assert forbidden not in payload


def test_token_expiry_follows_configuration(
    jwt_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "JWT_EXPIRE_MINUTES", 30)

    payload = jwt.decode(create_access_token(USER_ID), jwt_secret, algorithms=["HS256"])

    lifetime = payload["exp"] - payload["iat"]
    assert lifetime == 30 * 60
    assert token_lifetime_seconds() == 1800


def test_tokens_are_signed_not_merely_encoded(jwt_secret: str) -> None:
    token = create_access_token(USER_ID)

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "a-different-secret-of-sufficient-length-32b", algorithms=["HS256"])


# --- Token decoding ---------------------------------------------------------


def test_valid_token_round_trips(jwt_secret: str) -> None:
    payload = decode_access_token(create_access_token(USER_ID))

    assert payload["sub"] == USER_ID


@pytest.mark.parametrize("token", ["", "   ", None], ids=["empty", "spaces", "none"])
def test_missing_token_is_reported(jwt_secret: str, token) -> None:
    with pytest.raises(AppError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.code == "TOKEN_MISSING"
    assert exc_info.value.status_code == 401


def test_expired_token_is_reported(jwt_secret: str) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    expired = jwt.encode(
        {"sub": USER_ID, "iat": past, "exp": past + timedelta(minutes=1), "type": "access"},
        jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(AppError) as exc_info:
        decode_access_token(expired)

    assert exc_info.value.code == "TOKEN_EXPIRED"
    assert exc_info.value.status_code == 401


def test_token_signed_with_another_secret_is_rejected(jwt_secret: str) -> None:
    forged = jwt.encode(
        {
            "sub": USER_ID,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        "attacker-chosen-secret-of-sufficient-length",
        algorithm="HS256",
    )

    with pytest.raises(AppError) as exc_info:
        decode_access_token(forged)

    assert exc_info.value.code == "TOKEN_INVALID"


@pytest.mark.parametrize(
    "token",
    ["not.a.token", "abc", "a.b.c.d", "eyJhbGciOiJIUzI1NiJ9.garbage.sig"],
)
def test_malformed_tokens_are_rejected(jwt_secret: str, token: str) -> None:
    with pytest.raises(AppError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.code == "TOKEN_INVALID"


def test_token_without_a_subject_is_rejected(jwt_secret: str) -> None:
    no_sub = jwt.encode(
        {"iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1),
         "type": "access"},
        jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(AppError) as exc_info:
        decode_access_token(no_sub)

    assert exc_info.value.code == "TOKEN_INVALID"


def test_token_of_the_wrong_type_is_rejected(jwt_secret: str) -> None:
    """Guards the seam where refresh tokens would be added later."""
    refresh = jwt.encode(
        {
            "sub": USER_ID,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "refresh",
        },
        jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(AppError) as exc_info:
        decode_access_token(refresh)

    assert exc_info.value.code == "TOKEN_INVALID"


def test_unsigned_token_is_rejected(jwt_secret: str) -> None:
    """The classic alg=none attack must not work."""
    unsigned = jwt.encode(
        {
            "sub": USER_ID,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(AppError) as exc_info:
        decode_access_token(unsigned)

    assert exc_info.value.code == "TOKEN_INVALID"


# --- Missing configuration --------------------------------------------------


def test_creating_a_token_without_a_secret_fails_cleanly(no_jwt_secret: None) -> None:
    with pytest.raises(AppError) as exc_info:
        create_access_token(USER_ID)

    assert exc_info.value.code == "AUTH_NOT_CONFIGURED"
    assert exc_info.value.status_code == 503


def test_decoding_without_a_secret_fails_cleanly(no_jwt_secret: None) -> None:
    with pytest.raises(AppError) as exc_info:
        decode_access_token("any.token.value")

    assert exc_info.value.code == "AUTH_NOT_CONFIGURED"


def test_error_messages_never_contain_the_secret(jwt_secret: str) -> None:
    with pytest.raises(AppError) as exc_info:
        decode_access_token("garbage")

    assert jwt_secret not in exc_info.value.message
    assert jwt_secret not in str(exc_info.value.details or "")
