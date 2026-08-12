"""Shared test fixtures.

The fake client here lets every database test run offline. No test in this
suite opens a network connection, so the suite works for anyone who clones
the repository without a MongoDB Atlas account.
"""

from collections.abc import Iterator

import pytest
from pymongo.errors import ConnectionFailure

from app.config import settings
from app.database import mongodb

FAKE_URI = "mongodb+srv://fake-user:fake-pass@fake-cluster.example.net/"


class FakeAdmin:
    """Stands in for `client.admin`, the object the ping command runs on."""

    def __init__(self, should_fail: bool) -> None:
        self.should_fail = should_fail
        self.ping_count = 0

    def command(self, command_name: str) -> dict:
        self.ping_count += 1
        if self.should_fail:
            raise ConnectionFailure("simulated connection failure")
        return {"ok": 1.0}


class FakeMongoClient:
    """Minimal stand-in for pymongo.MongoClient."""

    def __init__(self, should_fail: bool = False) -> None:
        self.admin = FakeAdmin(should_fail)
        self.closed = False

    def __getitem__(self, name: str) -> str:
        return f"fake-database:{name}"

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def reset_mongodb_state() -> Iterator[None]:
    """Return the shared mongodb singleton to a clean state after each test.

    Without this, a test that fakes a connection would leak that state into
    the next test and make failures depend on ordering.
    """
    yield
    mongodb._client = None
    mongodb._connected = False


@pytest.fixture
def unconfigured_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate MONGODB_URI being absent."""
    monkeypatch.setattr(settings, "MONGODB_URI", None)
    mongodb._client = None
    mongodb._connected = False


@pytest.fixture
def connected_db(monkeypatch: pytest.MonkeyPatch) -> FakeMongoClient:
    """Simulate a configured database whose ping succeeds."""
    monkeypatch.setattr(settings, "MONGODB_URI", FAKE_URI)
    fake = FakeMongoClient(should_fail=False)
    mongodb._client = fake
    mongodb._connected = True
    return fake


@pytest.fixture
def failing_db(monkeypatch: pytest.MonkeyPatch) -> FakeMongoClient:
    """Simulate a configured database that cannot be reached."""
    monkeypatch.setattr(settings, "MONGODB_URI", FAKE_URI)
    fake = FakeMongoClient(should_fail=True)
    mongodb._client = fake
    mongodb._connected = True  # stale optimism; ping should correct it
    return fake
