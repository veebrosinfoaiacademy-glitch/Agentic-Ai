"""Phase 4 tests: Groq service logic, entirely offline.

No test here needs a real GROQ_API_KEY or network access.
"""

import httpx
import pytest
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)

from app.config import settings
from app.services.groq_service import GroqService, _scrub, groq_service
from app.utils.errors import AppError
from tests.conftest import FAKE_GROQ_KEY, FakeCompletion, install_fake_groq

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _status_error(cls: type, status: int, message: str = "failed"):
    """Build an SDK status exception with the httpx objects it requires."""
    return cls(message, response=httpx.Response(status, request=REQUEST), body=None)


# --- Test 1: missing API key ------------------------------------------------


def test_service_reports_unconfigured_without_key(groq_unconfigured: None) -> None:
    assert groq_service.is_configured is False


def test_generate_without_key_raises_ai_not_configured(
    groq_unconfigured: None,
) -> None:
    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="hello")

    assert exc_info.value.code == "AI_NOT_CONFIGURED"
    assert exc_info.value.status_code == 503
    assert exc_info.value.message == "AI service is not configured"


# --- Test 2: successful response --------------------------------------------


def test_generate_extracts_content_model_and_usage(groq_configured: None) -> None:
    install_fake_groq(FakeCompletion(content="  Recursion is self-reference.  "))

    result = groq_service.generate(user_prompt="Explain recursion.")

    assert result.content == "Recursion is self-reference."  # whitespace trimmed
    assert result.model == settings.GROQ_MODEL
    assert result.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_generate_sends_configured_model_and_both_messages(
    groq_configured: None,
) -> None:
    fake = install_fake_groq(FakeCompletion())

    groq_service.generate(user_prompt="Task", system_prompt="You are a reviewer.")

    call = fake.chat.completions.calls[0]
    assert call["model"] == settings.GROQ_MODEL
    assert call["messages"] == [
        {"role": "system", "content": "You are a reviewer."},
        {"role": "user", "content": "Task"},
    ]


def test_generate_omits_system_message_when_not_given(groq_configured: None) -> None:
    fake = install_fake_groq(FakeCompletion())

    groq_service.generate(user_prompt="Task")

    assert fake.chat.completions.calls[0]["messages"] == [
        {"role": "user", "content": "Task"}
    ]


def test_generate_passes_sampling_parameters(groq_configured: None) -> None:
    fake = install_fake_groq(FakeCompletion())

    groq_service.generate(user_prompt="Task", temperature=0.1, max_tokens=256)

    call = fake.chat.completions.calls[0]
    assert call["temperature"] == 0.1
    assert call["max_completion_tokens"] == 256


def test_generate_handles_missing_usage(groq_configured: None) -> None:
    """Usage is optional metadata; its absence must not break the call."""
    install_fake_groq(FakeCompletion(with_usage=False))

    assert groq_service.generate(user_prompt="Task").usage == {}


def test_client_is_reused_across_calls(groq_configured: None) -> None:
    """One client per process, not one per request."""
    fake = install_fake_groq(FakeCompletion())

    groq_service.generate(user_prompt="one")
    groq_service.generate(user_prompt="two")

    assert groq_service._client is fake
    assert len(fake.chat.completions.calls) == 2


# --- Test 3: provider failure -----------------------------------------------


@pytest.mark.parametrize(
    ("exception", "expected_code", "expected_status"),
    [
        (_status_error(BadRequestError, 400), "AI_PROVIDER_ERROR", 502),
        (_status_error(NotFoundError, 404), "AI_MODEL_UNAVAILABLE", 503),
        (
            APIConnectionError(request=REQUEST),
            "AI_PROVIDER_ERROR",
            502,
        ),
        (RuntimeError("something unexpected"), "AI_PROVIDER_ERROR", 502),
    ],
)
def test_provider_failures_map_to_app_errors(
    groq_configured: None,
    exception: Exception,
    expected_code: str,
    expected_status: int,
) -> None:
    install_fake_groq(exception)

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == expected_status


def test_empty_content_is_treated_as_a_provider_error(groq_configured: None) -> None:
    """An empty reply must not silently become empty article text."""
    install_fake_groq(FakeCompletion(content="   "))

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert exc_info.value.code == "AI_EMPTY_RESPONSE"


def test_missing_choices_is_treated_as_a_provider_error(groq_configured: None) -> None:
    install_fake_groq(FakeCompletion(with_choices=False))

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert exc_info.value.code == "AI_EMPTY_RESPONSE"


# --- Test 4: timeout --------------------------------------------------------


def test_timeout_maps_to_gateway_timeout(groq_configured: None) -> None:
    install_fake_groq(APITimeoutError(request=REQUEST))

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert exc_info.value.code == "AI_PROVIDER_TIMEOUT"
    assert exc_info.value.status_code == 504


# --- Rate limiting and authentication ---------------------------------------


def test_rate_limit_maps_to_429(groq_configured: None) -> None:
    install_fake_groq(_status_error(RateLimitError, 429))

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert exc_info.value.status_code == 429


def test_invalid_key_reports_not_configured_without_saying_why(
    groq_configured: None,
) -> None:
    """A bad key is a deployment problem; the user gets no detail about it."""
    install_fake_groq(_status_error(AuthenticationError, 401, "Invalid API Key"))

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert exc_info.value.code == "AI_NOT_CONFIGURED"
    assert "key" not in exc_info.value.message.lower()


# --- The API key must never escape ------------------------------------------


def test_scrub_removes_the_api_key(groq_configured: None) -> None:
    text = f"request failed with Authorization: Bearer {FAKE_GROQ_KEY}"

    scrubbed = _scrub(text)

    assert FAKE_GROQ_KEY not in scrubbed
    assert "***REDACTED***" in scrubbed


def test_user_facing_error_messages_never_contain_the_key(
    groq_configured: None,
) -> None:
    """Even if a provider echoed the key back, it cannot reach the client."""
    install_fake_groq(
        _status_error(BadRequestError, 400, f"bad request for key {FAKE_GROQ_KEY}")
    )

    with pytest.raises(AppError) as exc_info:
        groq_service.generate(user_prompt="Task")

    assert FAKE_GROQ_KEY not in exc_info.value.message
    assert FAKE_GROQ_KEY not in str(exc_info.value.details or "")


def test_close_releases_the_client(groq_configured: None) -> None:
    fake = install_fake_groq(FakeCompletion())
    groq_service.generate(user_prompt="Task")

    groq_service.close()

    assert fake.closed is True
    assert groq_service._client is None


def test_model_comes_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is exactly one source of truth for the model name."""
    monkeypatch.setattr(settings, "GROQ_MODEL", "some-other-model")

    assert GroqService().model == "some-other-model"
