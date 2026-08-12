"""Password hashing and JSON Web Token handling.

The only module that imports a hashing library or a JWT library. Services and
routes call these functions and never see an algorithm name, a salt or a
signing key — the same isolation `groq_service.py` gives the Groq SDK.

SECURITY: no function here ever logs a password, a hash, a token or the
signing secret. There is a test asserting that.
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import settings
from app.utils.errors import AppError

logger = logging.getLogger("app.security")

# Argon2id: memory-hard, so a stolen hash is expensive to attack even with a
# GPU. Chosen over bcrypt, which caps passwords at 72 bytes and raises above
# that. pwdlib handles salting and encodes the parameters into the hash
# string, so verification stays correct if we tune the cost later.
_password_hash = PasswordHash((Argon2Hasher(),))

TOKEN_TYPE = "access"


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A real hash to verify against when no user was found.

    Login must take similar work whether or not the email exists, otherwise
    response time alone reveals which addresses are registered. Computed once
    and cached; the value is arbitrary and never matches a real password.
    """
    return _password_hash.hash("not-a-real-password-placeholder")


def _signing_secret() -> str:
    """Return the JWT secret, or fail cleanly if it was never configured.

    Deliberately not checked at import time — the app must still start
    without a secret, exactly as it does without a Groq key or a database.
    Only the auth endpoints become unavailable.
    """
    if not settings.JWT_SECRET:
        logger.error("JWT_SECRET is not set - authentication is unavailable")
        raise AppError(
            code="AUTH_NOT_CONFIGURED",
            message="Authentication is not configured",
            status_code=503,
        )
    return settings.JWT_SECRET


# --- Passwords --------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id.

    The returned string carries the algorithm, parameters and salt, so
    nothing else needs storing.
    """
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a malformed or empty hash. A corrupt
    stored hash should fail the login, not crash the request with a 500 that
    tells the caller something unusual happened to that account.
    """
    if not password or not password_hash:
        return False
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        logger.warning("Password verification failed: stored hash is unusable")
        return False


def verify_dummy_password(password: str) -> bool:
    """Burn equivalent work when no user was found. Always returns False."""
    verify_password(password, _dummy_hash())
    return False


# --- Tokens -----------------------------------------------------------------


def token_lifetime_seconds() -> int:
    """Configured access token lifetime, in seconds."""
    return settings.JWT_EXPIRE_MINUTES * 60


def create_access_token(subject: str) -> str:
    """Issue a signed access token for a user id.

    Claims are deliberately minimal — the subject, when it was issued, when
    it expires, and its type. A JWT is signed but NOT encrypted: anyone
    holding it can read the payload, so it carries no email, no password, no
    hash and no user document.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "type": TOKEN_TYPE,
    }
    return jwt.encode(payload, _signing_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify and decode an access token.

    Signature and expiry are checked by PyJWT. Everything that fails becomes
    a clean AppError — a decoding traceback would tell an attacker which part
    of the token they got wrong.
    """
    if not token or not token.strip():
        raise AppError(
            code="TOKEN_MISSING",
            message="Authentication token is missing",
            status_code=401,
        )

    try:
        payload = jwt.decode(
            token,
            _signing_secret(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise AppError(
            code="TOKEN_EXPIRED",
            message="Authentication token has expired",
            status_code=401,
        ) from None
    except jwt.InvalidTokenError:
        # Covers a bad signature, a malformed token, a missing required
        # claim and an unexpected algorithm. All look identical to the client.
        raise AppError(
            code="TOKEN_INVALID",
            message="Authentication token is invalid",
            status_code=401,
        ) from None

    # A refresh token, once one exists, must not open an access-only route.
    if payload.get("type") != TOKEN_TYPE:
        raise AppError(
            code="TOKEN_INVALID",
            message="Authentication token is invalid",
            status_code=401,
        )

    return payload
