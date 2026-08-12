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
from app.services.groq_service import groq_service

FAKE_URI = "mongodb+srv://fake-user:fake-pass@fake-cluster.example.net/"
FAKE_GROQ_KEY = "gsk_fake_test_key_do_not_use"
FAKE_MODEL = "llama-3.3-70b-versatile"


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
def reset_singletons() -> Iterator[None]:
    """Return the shared singletons to a clean state after each test.

    Without this, a test that fakes a connection would leak that state into
    the next test and make failures depend on ordering.
    """
    yield
    mongodb._client = None
    mongodb._connected = False
    groq_service._client = None


# --- Groq fakes -------------------------------------------------------------
#
# These mirror only the parts of the SDK response the service actually reads,
# so no test needs a real API key or a network connection.


class FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = FakeMessage(content)


class FakeUsage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class FakeCompletion:
    """Stands in for the object returned by chat.completions.create()."""

    def __init__(
        self,
        content: str | None = "Hello from a fake model.",
        model: str = FAKE_MODEL,
        with_usage: bool = True,
        with_choices: bool = True,
    ) -> None:
        self.choices = [FakeChoice(content)] if with_choices else []
        self.model = model
        self.usage = FakeUsage(12, 8) if with_usage else None


class FakeCompletions:
    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGroqClient:
    """Minimal stand-in for groq.Groq."""

    def __init__(self, result: object | Exception) -> None:
        self.chat = type("FakeChat", (), {"completions": FakeCompletions(result)})()
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def groq_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate GROQ_API_KEY being present, without a real key."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", FAKE_GROQ_KEY)
    monkeypatch.setattr(settings, "GROQ_MODEL", FAKE_MODEL)
    groq_service._client = None


@pytest.fixture
def groq_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate GROQ_API_KEY being absent."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", None)
    groq_service._client = None


def install_fake_groq(result: object | Exception) -> FakeGroqClient:
    """Attach a fake client to the shared service and return it.

    Use together with the `groq_configured` fixture.
    """
    fake = FakeGroqClient(result)
    groq_service._client = fake
    return fake


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
