"""User registration, login and lookup.

Sits between the routes and MongoDB. Routes never query the database, never
hash a password and never build a token; this module coordinates those, and
`utils/security.py` performs them.

Uses the existing process-level MongoClient through `get_users_collection()`.
No second client, and no connection opened per request.
"""

import logging
from datetime import UTC, datetime

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.database import get_users_collection
from app.schemas.auth_schemas import TokenData, UserData
from app.utils.errors import AppError
from app.utils.security import (
    create_access_token,
    hash_password,
    token_lifetime_seconds,
    verify_dummy_password,
    verify_password,
)

logger = logging.getLogger("app.auth")

# One message and one status for every credential failure. See authenticate().
_AUTH_FAILED = AppError(
    code="AUTHENTICATION_FAILED",
    message="Invalid email or password",
    status_code=401,
)


def _auth_failed() -> AppError:
    """Fresh instance each time, so a raise site never mutates a shared one."""
    return AppError(
        code=_AUTH_FAILED.code,
        message=_AUTH_FAILED.message,
        status_code=_AUTH_FAILED.status_code,
    )


def _database_unavailable(exc: PyMongoError) -> AppError:
    """MongoDB could not answer.

    Authentication must fail closed. Returning a token because we could not
    reach the database would authenticate everyone during an outage.
    """
    logger.error("Auth database operation failed: %s", type(exc).__name__)
    return AppError(
        code="DATABASE_UNAVAILABLE",
        message="The service is temporarily unavailable. Please try again.",
        status_code=503,
    )


def _to_user_data(document: dict) -> UserData:
    """Convert a stored user document into its public representation.

    Builds an explicit UserData rather than filtering the document. A
    denylist ("remove password_hash") fails open when a new sensitive field
    is added later; naming the three public fields fails closed.
    """
    return UserData(
        id=str(document["_id"]),
        email=document["email"],
        created_at=document["created_at"],
    )


class AuthService:
    """Registration, authentication and user lookup."""

    def register(self, email: str, password: str) -> UserData:
        """Create a new account.

        The email is already normalised by the request schema. Uniqueness is
        enforced by the unique index rather than by a read-then-write check,
        which would race under concurrent registrations.
        """
        users = get_users_collection()
        now = datetime.now(UTC)

        document = {
            "email": email,
            # Only ever the hash. The plaintext exists as a local variable
            # for the duration of this call and is never stored or logged.
            "password_hash": hash_password(password),
            "created_at": now,
            "updated_at": now,
        }

        try:
            result = users.insert_one(document)
        except DuplicateKeyError:
            # Registration is one of the few places where confirming an
            # address exists is unavoidable — the user has to be told why
            # their signup failed.
            logger.info("Registration rejected: email already registered")
            raise AppError(
                code="USER_ALREADY_EXISTS",
                message="An account with this email already exists",
                status_code=409,
            ) from None
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        logger.info("User registered: %s", result.inserted_id)

        document["_id"] = result.inserted_id
        return _to_user_data(document)

    def authenticate(self, email: str, password: str) -> TokenData:
        """Verify credentials and issue an access token.

        A missing account and a wrong password produce the identical error,
        and both do comparable hashing work — see verify_dummy_password.
        Returning "user not found" would let anyone test which addresses are
        registered.
        """
        users = get_users_collection()

        try:
            document = users.find_one({"email": email})
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        if document is None:
            # Hash anyway so the response time does not reveal the miss.
            verify_dummy_password(password)
            logger.info("Login failed: no account for the supplied email")
            raise _auth_failed()

        if not verify_password(password, document.get("password_hash", "")):
            logger.info("Login failed: incorrect password for %s", document["_id"])
            raise _auth_failed()

        logger.info("Login succeeded for %s", document["_id"])

        return TokenData(
            access_token=create_access_token(str(document["_id"])),
            token_type="bearer",
            expires_in=token_lifetime_seconds(),
        )

    def get_user_by_id(self, user_id: str) -> UserData:
        """Load a user by the id carried in a token's `sub` claim.

        A token can outlive the account it names, and `sub` is attacker-
        influenced in the sense that a forged token could carry anything.
        Both cases produce the same 401.
        """
        # ObjectId(None) does NOT raise — it silently generates a new random
        # id, which would turn a null subject into a lookup for an arbitrary
        # user. The type check has to come first.
        if not isinstance(user_id, str) or not user_id.strip():
            logger.warning("Token carried an empty or non-string user id")
            raise AppError(
                code="TOKEN_INVALID",
                message="Authentication token is invalid",
                status_code=401,
            )

        try:
            object_id = ObjectId(user_id)
        except (InvalidId, TypeError):
            # Never let a malformed id reach PyMongo and surface as a 500.
            logger.warning("Token carried a malformed user id")
            raise AppError(
                code="TOKEN_INVALID",
                message="Authentication token is invalid",
                status_code=401,
            ) from None

        users = get_users_collection()

        try:
            document = users.find_one({"_id": object_id})
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        if document is None:
            logger.warning("Token referenced a user that no longer exists")
            raise AppError(
                code="USER_NOT_FOUND",
                message="Authentication token is invalid",
                status_code=401,
            )

        return _to_user_data(document)


# Single shared instance, matching the project's service pattern.
auth_service = AuthService()
