"""Phase 4 tests: the POST /api/ai/test endpoint.

These check the HTTP contract — validation, envelopes, status codes — with
the Groq service faked out.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ai_schemas import MAX_PROMPT_CHARS
from app.utils.errors import AppError
from tests.conftest import FakeCompletion, install_fake_groq

client = TestClient(app)

ENDPOINT = "/api/ai/test"


# --- Test 5: successful request through the endpoint ------------------------


def test_returns_standard_success_envelope(groq_configured: None) -> None:
    install_fake_groq(FakeCompletion(content="An AI agent acts on your behalf."))

    response = client.post(ENDPOINT, json={"prompt": "What is an AI agent?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"success", "message", "data"}
    assert body["success"] is True
    assert body["message"] == "AI request completed"
    assert body["data"]["content"] == "An AI agent acts on your behalf."
    assert body["data"]["model"]
    assert body["data"]["usage"]["total_tokens"] == 20


def test_endpoint_appears_in_openapi_schema() -> None:
    schema = client.get("/openapi.json").json()

    assert ENDPOINT in schema["paths"]
    assert "post" in schema["paths"][ENDPOINT]


def test_client_cannot_supply_an_api_key(groq_configured: None) -> None:
    """The request schema has exactly one field. Keys come from the server.

    `extra` fields are ignored by Pydantic here, so a client-sent key is
    silently discarded rather than used.
    """
    schema = client.get("/openapi.json").json()
    request_schema = schema["components"]["schemas"]["AITestRequest"]

    assert list(request_schema["properties"]) == ["prompt"]

    fake = install_fake_groq(FakeCompletion())
    client.post(
        ENDPOINT, json={"prompt": "hi", "api_key": "gsk_attacker_supplied_key"}
    )

    call = fake.chat.completions.calls[0]
    assert "api_key" not in call


# --- Test 6: input validation -----------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": ""},
        {"prompt": "   "},
        {"prompt": "\n\t "},
        {},
        {"prompt": None},
    ],
    ids=["empty", "spaces", "whitespace", "missing", "null"],
)
def test_invalid_prompts_are_rejected(
    groq_configured: None, payload: dict
) -> None:
    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"][0]["field"] == "prompt"


def test_oversized_prompt_is_rejected(groq_configured: None) -> None:
    response = client.post(ENDPOINT, json={"prompt": "a" * (MAX_PROMPT_CHARS + 1)})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_prompt_at_the_limit_is_accepted(groq_configured: None) -> None:
    install_fake_groq(FakeCompletion())

    response = client.post(ENDPOINT, json={"prompt": "a" * MAX_PROMPT_CHARS})

    assert response.status_code == 200


def test_prompt_is_stripped_before_reaching_the_service(
    groq_configured: None,
) -> None:
    fake = install_fake_groq(FakeCompletion())

    client.post(ENDPOINT, json={"prompt": "  Explain recursion.  "})

    messages = fake.chat.completions.calls[0]["messages"]
    assert messages[-1]["content"] == "Explain recursion."


# --- Service errors surface through the Phase 2 error envelope --------------


def test_missing_api_key_returns_503_envelope(groq_unconfigured: None) -> None:
    response = client.post(ENDPOINT, json={"prompt": "hello"})

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "message": "AI service is not configured",
        "error": {"code": "AI_NOT_CONFIGURED", "details": None},
    }


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AI_PROVIDER_TIMEOUT", 504),
        ("AI_RATE_LIMITED", 429),
        ("AI_PROVIDER_ERROR", 502),
    ],
)
def test_service_errors_reach_the_client_as_error_envelopes(
    monkeypatch: pytest.MonkeyPatch, code: str, status: int
) -> None:
    def raise_error(**_: object) -> None:
        raise AppError(code=code, message="AI service problem", status_code=status)

    monkeypatch.setattr("app.routes.ai.groq_service.generate", raise_error)

    response = client.post(ENDPOINT, json={"prompt": "hello"})

    assert response.status_code == status
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code


def test_unexpected_service_crash_does_not_leak_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bug in the service must not expose a traceback to the caller."""

    def explode(**_: object) -> None:
        raise RuntimeError("secret internal detail at /Users/someone/app.py")

    monkeypatch.setattr("app.routes.ai.groq_service.generate", explode)

    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.post(ENDPOINT, json={"prompt": "hello"})

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "message": "Internal server error",
        "error": {"code": "INTERNAL_SERVER_ERROR", "details": None},
    }
    assert "secret internal detail" not in response.text
