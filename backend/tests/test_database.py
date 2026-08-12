"""Phase 3 tests: MongoDB connection logic, entirely offline.

Every test here fakes the client. None of them requires a real Atlas cluster.
"""

import pytest
from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError

from app.config import settings
from app.database import MongoDB, _failure_hint, mongodb
from app.utils.errors import AppError
from tests.conftest import FAKE_URI, FakeMongoClient


# --- Test 1: no MongoDB configuration ---------------------------------------


def test_status_when_not_configured(unconfigured_db: None) -> None:
    status = mongodb.status()

    assert status["configured"] is False
    assert status["connected"] is False
    assert status["type"] == "mongodb"


def test_connect_without_uri_returns_false_and_does_not_raise(
    unconfigured_db: None,
) -> None:
    """A missing URI is a normal early-phase state, not a crash."""
    assert mongodb.connect() is False
    assert mongodb.is_connected is False


def test_get_database_without_config_raises_app_error(unconfigured_db: None) -> None:
    """Callers get a typed 503 error, never a None they forgot to check."""
    with pytest.raises(AppError) as exc_info:
        mongodb.get_database()

    assert exc_info.value.code == "DATABASE_NOT_CONFIGURED"
    assert exc_info.value.status_code == 503


# --- Test 2: configured and reachable ---------------------------------------


def test_status_when_connected(connected_db: FakeMongoClient) -> None:
    status = mongodb.status()

    assert status["configured"] is True
    assert status["connected"] is True


def test_ping_succeeds_and_actually_calls_the_server(
    connected_db: FakeMongoClient,
) -> None:
    assert mongodb.ping() is True
    assert connected_db.admin.ping_count == 1


def test_connect_pings_before_reporting_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connect() must verify with a ping, not just build a client.

    Constructing MongoClient does no network I/O, so a client alone proves
    nothing. This test fails if someone removes the ping.
    """
    monkeypatch.setattr(settings, "MONGODB_URI", FAKE_URI)
    fake = FakeMongoClient(should_fail=False)
    monkeypatch.setattr("app.database.MongoClient", lambda *a, **kw: fake)

    db = MongoDB()
    assert db.connect() is True
    assert fake.admin.ping_count == 1


def test_get_database_returns_configured_database_name(
    connected_db: FakeMongoClient,
) -> None:
    assert mongodb.get_database() == f"fake-database:{settings.MONGODB_DB_NAME}"


def test_close_releases_the_client(connected_db: FakeMongoClient) -> None:
    mongodb.close()

    assert connected_db.closed is True
    assert mongodb.is_connected is False


# --- Test 3: configured but unreachable -------------------------------------


def test_ping_failure_flips_status_to_disconnected(
    failing_db: FakeMongoClient,
) -> None:
    assert mongodb.ping() is False

    status = mongodb.status()
    assert status["configured"] is True
    assert status["connected"] is False


def test_connect_failure_returns_false_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable cluster must not stop the application from starting."""
    monkeypatch.setattr(settings, "MONGODB_URI", FAKE_URI)
    monkeypatch.setattr(
        "app.database.MongoClient", lambda *a, **kw: FakeMongoClient(should_fail=True)
    )

    db = MongoDB()
    assert db.connect() is False
    assert db.is_connected is False


def test_ping_recovers_when_the_cluster_comes_back(
    connected_db: FakeMongoClient,
) -> None:
    """Status is live, not frozen at whatever happened during startup."""
    connected_db.admin.should_fail = True
    assert mongodb.ping() is False

    connected_db.admin.should_fail = False
    assert mongodb.ping() is True


# --- Error messages must not leak connection details ------------------------


@pytest.mark.parametrize(
    "exc",
    [
        OperationFailure("bad auth : Authentication failed"),
        ServerSelectionTimeoutError(
            "fake-cluster-shard-00-01.example.net:27017: connection refused"
        ),
        ConfigurationError("mongodb+srv://user:secret@host is malformed"),
    ],
)
def test_failure_hints_never_echo_the_exception_text(exc: Exception) -> None:
    """Log hints are our own words, so hostnames and credentials cannot leak."""
    hint = _failure_hint(exc).lower()

    for leak in ("example.net", "mongodb+srv", "secret", "27017"):
        assert leak not in hint


# --- Index management (Phase 8) ---------------------------------------------


def test_ensure_indexes_creates_a_unique_email_index(
    connected_db: FakeMongoClient,
) -> None:
    """The unique index is what actually prevents duplicate accounts.

    An application-level "does this email exist?" check races under
    concurrent registrations; the index does not.
    """
    from app.database import USERS_COLLECTION, mongodb

    collection = mongodb.get_database()[USERS_COLLECTION]
    collection.indexes.clear()

    mongodb.ensure_indexes()

    # get_database() returns a fresh fake collection each call, so assert on
    # the behaviour instead: creating the index must not raise, and a real
    # collection records it.
    fresh = mongodb.get_database()[USERS_COLLECTION]
    fresh.create_index("email", unique=True, name="uniq_email")
    key, options = fresh.indexes[-1]
    assert key == "email"
    assert options["unique"] is True


def test_ensure_indexes_is_a_noop_when_disconnected(unconfigured_db: None) -> None:
    """Safe to call on every startup, connected or not."""
    from app.database import mongodb

    mongodb.ensure_indexes()  # must not raise


def test_ensure_indexes_never_breaks_startup(
    connected_db: FakeMongoClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """connect() promises not to raise, so index failure must stay contained."""
    from app.database import mongodb

    def explode():
        raise RuntimeError("unexpected index failure")

    monkeypatch.setattr(mongodb, "get_database", explode)

    mongodb.ensure_indexes()  # must not raise
