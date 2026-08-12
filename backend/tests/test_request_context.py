"""Phase 12 tests: request correlation ids.

Two things matter: an id reaches every response and every log line, and an
inbound id can never inject into a log file.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.utils.request_context import (
    MAX_REQUEST_ID_LENGTH,
    REQUEST_ID_HEADER,
    RequestIdFilter,
    get_request_id,
    new_request_id,
    sanitise_request_id,
    set_request_id,
)
from tests.conftest import FakeCollection, FakeUsersCollection

client = TestClient(app)


# --- Sanitising -------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        "abc123",
        "550e8400-e29b-41d4-a716-446655440000",  # UUID
        "01ARZ3NDEKTSV4RRFFQ69G5FAV",  # ULID
        "trace_id-123",
        "A" * MAX_REQUEST_ID_LENGTH,
    ],
    ids=["simple", "uuid", "ulid", "underscore-dash", "max-length"],
)
def test_acceptable_ids_are_preserved(candidate: str) -> None:
    """A client's own trace id survives, so their logs and ours line up."""
    assert sanitise_request_id(candidate) == candidate


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        "   ",
        "A" * (MAX_REQUEST_ID_LENGTH + 1),
        "has spaces",
        "semi;colon",
        "../../etc/passwd",
        "<script>alert(1)</script>",
        "id\nINFO fake log line",
        "id\r\nWARNING forged",
        "id\x00null",
        "unicode-→-arrow",
        "%0aInjected",
    ],
    ids=[
        "none", "empty", "spaces", "too-long", "space", "semicolon", "traversal",
        "html", "newline", "crlf", "null-byte", "unicode", "encoded-newline",
    ],
)
def test_unacceptable_ids_are_replaced(candidate) -> None:
    """Replaced, not cleaned.

    Stripping bad characters would silently change the id the client believes
    it sent, which correlates nothing. A fresh id is honest.
    """
    result = sanitise_request_id(candidate)

    assert result != candidate
    assert result.isalnum()
    assert len(result) == 16


def test_newlines_can_never_reach_a_log_line() -> None:
    """The log-injection case, stated directly."""
    forged = "abc\nERROR  | app | Everything is fine"

    assert "\n" not in sanitise_request_id(forged)


def test_generated_ids_are_unique() -> None:
    assert len({new_request_id() for _ in range(200)}) == 200


# --- Context binding --------------------------------------------------------


def test_the_id_is_readable_from_anywhere_in_the_request() -> None:
    set_request_id("bound-id")

    assert get_request_id() == "bound-id"


def test_outside_a_request_the_id_is_a_placeholder() -> None:
    set_request_id("-")

    assert get_request_id() == "-"


def test_the_logging_filter_supplies_the_id() -> None:
    set_request_id("filter-test-id")
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "msg", None, None)

    RequestIdFilter().filter(record)

    assert record.request_id == "filter-test-id"


# --- Responses --------------------------------------------------------------


def test_every_response_carries_a_request_id(unconfigured_db: None) -> None:
    response = client.get("/api/health")

    assert REQUEST_ID_HEADER in response.headers
    assert len(response.headers[REQUEST_ID_HEADER]) == 16


def test_an_acceptable_inbound_id_is_echoed_back(unconfigured_db: None) -> None:
    response = client.get(
        "/api/health", headers={REQUEST_ID_HEADER: "client-trace-42"}
    )

    assert response.headers[REQUEST_ID_HEADER] == "client-trace-42"


def test_an_unsafe_inbound_id_is_replaced_in_the_response(
    unconfigured_db: None,
) -> None:
    response = client.get(
        "/api/health", headers={REQUEST_ID_HEADER: "bad id with spaces"}
    )

    assert response.headers[REQUEST_ID_HEADER] != "bad id with spaces"
    assert response.headers[REQUEST_ID_HEADER].isalnum()


def test_error_responses_carry_a_request_id_too() -> None:
    """The case that matters most — a user reporting a failure."""
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert REQUEST_ID_HEADER in response.headers


@pytest.mark.parametrize(
    ("method", "path", "payload", "expected"),
    [
        ("get", "/api/usage", None, 401),
        ("post", "/api/content/summarize", {"text": "x", "summary_type": "short"}, 401),
        ("get", "/api/nope", None, 404),
    ],
    ids=["unauthorised", "unauthorised-ai", "not-found"],
)
def test_failures_of_every_kind_are_traceable(
    method: str, path: str, payload, expected: int
) -> None:
    response = getattr(client, method)(path, **({"json": payload} if payload else {}))

    assert response.status_code == expected
    assert REQUEST_ID_HEADER in response.headers


def test_each_request_gets_its_own_id(unconfigured_db: None) -> None:
    first = client.get("/api/health").headers[REQUEST_ID_HEADER]
    second = client.get("/api/health").headers[REQUEST_ID_HEADER]

    assert first != second


# --- The envelope is untouched ----------------------------------------------


def test_the_request_id_is_absent_from_the_success_envelope(
    unconfigured_db: None,
) -> None:
    """Several test modules assert the envelope by exact equality, and a
    header is the conventional home for correlation data anyway."""
    body = client.get("/api/health").json()

    assert set(body.keys()) == {"success", "message", "data"}
    assert "request_id" not in str(body)


def test_the_request_id_is_absent_from_the_error_envelope() -> None:
    response = client.get("/api/does-not-exist")
    body = response.json()

    assert set(body.keys()) == {"success", "message", "error"}
    assert set(body["error"].keys()) == {"code", "details"}
    assert response.headers[REQUEST_ID_HEADER] not in response.text


# --- Logging ----------------------------------------------------------------


def test_the_id_appears_in_log_records(
    users: FakeUsersCollection, jwt_secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A support request quotes the header; this is what makes it findable."""
    with caplog.at_level("INFO"):
        response = client.post(
            "/api/auth/register",
            json={"email": "traced@example.com", "password": "trace-passphrase-x"},
            headers={REQUEST_ID_HEADER: "traceable-id-99"},
        )

    assert response.status_code == 201
    assert any(
        getattr(record, "request_id", None) == "traceable-id-99"
        for record in caplog.records
    )


def test_logs_never_contain_an_authorization_header(
    users: FakeUsersCollection,
    jwt_secret: str,
    conversations: FakeCollection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.services.auth_service import auth_service

    auth_service.register("logsafe@example.com", "log-safety-passphrase")
    token = auth_service.authenticate(
        "logsafe@example.com", "log-safety-passphrase"
    ).access_token

    with caplog.at_level("DEBUG"):
        client.get("/api/conversations", headers={"Authorization": f"Bearer {token}"})

    assert token not in caplog.text
    assert "Authorization" not in caplog.text
    assert "Bearer" not in caplog.text


def test_a_forged_id_cannot_fabricate_a_log_record(
    unconfigured_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    """End to end: the newline never reaches the log."""
    with caplog.at_level("INFO"):
        client.get(
            "/api/health",
            headers={REQUEST_ID_HEADER: "x\nCRITICAL | app | database deleted"},
        )

    assert "database deleted" not in caplog.text
    for record in caplog.records:
        assert "\n" not in getattr(record, "request_id", "")
