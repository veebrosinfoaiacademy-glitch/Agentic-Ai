"""MongoDB Atlas connection, managed for the lifetime of the application.

One MongoClient is created at startup and reused for every request. This
matters: MongoClient owns an internal connection pool, so creating one per
request would open and discard TCP connections constantly and exhaust Atlas's
connection limit on the free tier.

Nothing outside this module should import pymongo or know the connection
string exists. Routes and services ask for `get_database()` and get a handle.

Planned indexes (created in the phase that introduces each collection, not
here — an index on a collection that does not exist yet is noise):

    users           email                  -> unique
    conversations   user_id + created_at   -> compound
    documents       user_id + created_at   -> compound
    code_reviews    user_id + created_at   -> compound
"""

import logging

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from app.config import settings
from app.utils.errors import AppError

logger = logging.getLogger("app.database")

# Collection names live here so no other module hardcodes a string.
USERS_COLLECTION = "users"
CONVERSATIONS_COLLECTION = "conversations"
MESSAGES_COLLECTION = "messages"
USAGE_COLLECTION = "usage"
DOCUMENTS_COLLECTION = "documents"

# How long to wait for Atlas before giving up. The PyMongo default is 30s,
# which would make a misconfigured cluster look like a hung server.
SERVER_SELECTION_TIMEOUT_MS = 5000
CONNECT_TIMEOUT_MS = 5000


def _failure_hint(exc: PyMongoError) -> str:
    """Turn a PyMongo exception into a safe, actionable log message.

    We deliberately return our own text rather than str(exc). PyMongo error
    messages embed the cluster hostnames and replica set topology, and we do
    not want those in logs that might be shared or shipped somewhere.
    """
    if isinstance(exc, OperationFailure):
        return "authentication failed - check the database username and password"
    if isinstance(exc, ServerSelectionTimeoutError):
        return (
            "could not reach the cluster - check Atlas Network Access allows "
            "your IP address and the cluster is running"
        )
    if isinstance(exc, ConfigurationError):
        return "invalid connection string format - check MONGODB_URI"
    return "unexpected database error"


class MongoDB:
    """Holds the single MongoClient and reports its state.

    State lives on one instance rather than in loose module-level variables,
    so tests can swap it out and there is exactly one owner of the client.
    """

    def __init__(self) -> None:
        self._client: MongoClient | None = None
        self._connected: bool = False

    @property
    def is_configured(self) -> bool:
        """True when MONGODB_URI has been set in the environment."""
        return bool(settings.MONGODB_URI)

    @property
    def is_connected(self) -> bool:
        """Result of the most recent ping. Not re-checked here."""
        return self._connected

    def connect(self) -> bool:
        """Create the client and verify the connection with a ping.

        Returns True on success. Never raises: a missing or broken database
        should not stop the API process from starting (see docs/ and the
        Phase 3 notes for why).
        """
        if not self.is_configured:
            logger.warning(
                "MONGODB_URI is not set - starting without a database. "
                "Database-backed features will be unavailable."
            )
            self._connected = False
            return False

        try:
            self._client = MongoClient(
                settings.MONGODB_URI,
                serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
                connectTimeoutMS=CONNECT_TIMEOUT_MS,
                appname="ai-productivity-agents",
            )
            # Constructing MongoClient is lazy — it does no network I/O and
            # succeeds even against a hostname that does not exist. The ping
            # is what actually proves we can talk to Atlas.
            self._client.admin.command("ping")
        except PyMongoError as exc:
            self._connected = False
            logger.error(
                "MongoDB connection failed (%s): %s",
                type(exc).__name__,
                _failure_hint(exc),
            )
            return False

        self._connected = True
        logger.info(
            "MongoDB connected - database '%s'", settings.MONGODB_DB_NAME
        )
        self.ensure_indexes()
        return True

    def ping(self) -> bool:
        """Re-check connectivity right now and update the cached state.

        Called by the health endpoint so it reports live truth rather than
        whatever happened at startup. If the cluster went down after startup
        this flips to False; if it recovered, this flips back to True.
        """
        if not self.is_configured or self._client is None:
            self._connected = False
            return False

        try:
            self._client.admin.command("ping")
        except PyMongoError as exc:
            if self._connected:
                logger.error(
                    "MongoDB ping failed (%s): %s",
                    type(exc).__name__,
                    _failure_hint(exc),
                )
            self._connected = False
            return False

        self._connected = True
        return True

    def get_database(self) -> Database:
        """Return the database handle for services to query.

        Raises AppError (-> 503 through the Phase 2 handlers) when the
        database is unusable, so callers never get a None they forgot to check.
        """
        if self._client is None or not self.is_configured:
            raise AppError(
                code="DATABASE_NOT_CONFIGURED",
                message="Database is not configured",
                status_code=503,
            )
        return self._client[settings.MONGODB_DB_NAME]

    def ensure_indexes(self) -> None:
        """Create the indexes the application relies on.

        Idempotent: MongoDB ignores create_index for an index that already
        exists with the same definition, so this is safe to run on every
        startup. Never called per request.

        The unique index on users.email is not just an optimisation. Checking
        "does this email exist?" in application code and then inserting is a
        race: two simultaneous registrations can both pass the check. The
        index is what actually guarantees one account per address, and the
        service treats DuplicateKeyError as the authoritative answer.
        """
        if self._client is None or not self._connected:
            return

        try:
            database = self.get_database()
            database[USERS_COLLECTION].create_index(
                "email", unique=True, name="uniq_email"
            )

            # Every conversation query filters by user_id, so it leads both
            # indexes. Sorting by updated_at descending serves the list view
            # directly from the index rather than sorting in memory.
            database[CONVERSATIONS_COLLECTION].create_index(
                [("user_id", 1), ("updated_at", -1)], name="user_recent"
            )

            # Transcript reads: all messages for one conversation, oldest
            # first. conversation_id alone would do, but including user_id
            # means the ownership filter is also covered by the index.
            database[MESSAGES_COLLECTION].create_index(
                [("conversation_id", 1), ("created_at", 1)], name="conversation_timeline"
            )
            database[MESSAGES_COLLECTION].create_index(
                [("user_id", 1), ("conversation_id", 1)], name="user_conversation"
            )

            # One document per (user, window kind, window start). The unique
            # index is what makes the atomic upsert safe: two concurrent
            # requests cannot create two counters for the same window.
            database[USAGE_COLLECTION].create_index(
                [("user_id", 1), ("window", 1), ("window_start", 1)],
                unique=True,
                name="uniq_user_window",
            )
            # MongoDB expires spent windows itself. This is a database
            # feature, not a background worker.
            database[USAGE_COLLECTION].create_index(
                "window_start",
                expireAfterSeconds=settings.USAGE_RETENTION_DAYS * 24 * 60 * 60,
                name="usage_ttl",
            )

            # The only list query: this user's documents, newest first.
            # Nothing sorts by updated_at, so no second index is added.
            database[DOCUMENTS_COLLECTION].create_index(
                [("user_id", 1), ("created_at", -1)], name="user_documents"
            )

            logger.info("Database indexes ensured")
        except PyMongoError as exc:
            # A failure here must not stop the application from starting; the
            # affected feature will report its own error when used.
            logger.error(
                "Could not ensure indexes (%s): %s",
                type(exc).__name__,
                _failure_hint(exc),
            )
        except Exception as exc:
            # connect() promises never to raise. Anything unexpected here must
            # not take the whole application down at startup.
            logger.error("Could not ensure indexes (%s)", type(exc).__name__)

    def status(self) -> dict[str, object]:
        """Connection state for the health endpoint.

        Reports booleans only — never the URI, host, username or password.
        """
        return {
            "configured": self.is_configured,
            "connected": self._connected,
            "type": "mongodb",
        }

    def close(self) -> None:
        """Release the connection pool on application shutdown."""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.info("MongoDB connection closed")
        self._connected = False


# The single application-wide instance.
mongodb = MongoDB()


def get_database() -> Database:
    """Convenience accessor, usable as a FastAPI dependency in later phases."""
    return mongodb.get_database()


def get_users_collection() -> Collection:
    """Handle for the users collection.

    Services call this rather than indexing the database themselves, so the
    collection name exists in exactly one place.
    """
    return mongodb.get_database()[USERS_COLLECTION]


def get_conversations_collection() -> Collection:
    """Handle for the conversations collection."""
    return mongodb.get_database()[CONVERSATIONS_COLLECTION]


def get_messages_collection() -> Collection:
    """Handle for the messages collection."""
    return mongodb.get_database()[MESSAGES_COLLECTION]


def get_usage_collection() -> Collection:
    """Handle for the AI usage counters."""
    return mongodb.get_database()[USAGE_COLLECTION]


def get_documents_collection() -> Collection:
    """Handle for persisted documents."""
    return mongodb.get_database()[DOCUMENTS_COLLECTION]
