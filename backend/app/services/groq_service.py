"""Groq API communication.

This is the only module in the project that imports the Groq SDK. Agents in
later phases build prompts and hand them here; they never see a Groq client,
a model ID or an SDK exception. Swapping providers means rewriting this file
and nothing else.

Deliberately knows nothing about content, code, MongoDB, or HTTP. It takes a
system prompt and a user prompt, and returns generated text.
"""

import logging
from dataclasses import dataclass, field

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    Groq,
    GroqError,
    NotFoundError,
    RateLimitError,
)

from app.config import settings
from app.utils.errors import AppError

logger = logging.getLogger("app.groq")

# Defaults for a general request. Agents override these per task.
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048


@dataclass
class GroqResult:
    """What the service returns to its callers.

    A plain dataclass rather than a Pydantic API schema on purpose: the
    service layer should not depend on the shape of our HTTP responses.
    Routes decide what part of this to expose.
    """

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


def _scrub(text: str) -> str:
    """Remove the API key from a string before it is logged.

    Provider error messages are not supposed to contain credentials, but
    "not supposed to" is not a guarantee. This makes it one.
    """
    key = settings.GROQ_API_KEY
    if key and key in text:
        return text.replace(key, "***REDACTED***")
    return text


class GroqService:
    """Reusable Groq client wrapper."""

    def __init__(self) -> None:
        self._client: Groq | None = None

    @property
    def is_configured(self) -> bool:
        """True when GROQ_API_KEY is present in the environment."""
        return bool(settings.GROQ_API_KEY)

    @property
    def model(self) -> str:
        """The single source of truth for which model we call."""
        return settings.GROQ_MODEL

    def _get_client(self) -> Groq:
        """Return the shared client, creating it on first use.

        Built lazily rather than at import time so the application can still
        start without a key — the same fail-soft rule we used for MongoDB.
        The SDK client is thread-safe and pools connections, so one instance
        serves the whole process.
        """
        if not self.is_configured:
            raise AppError(
                code="AI_NOT_CONFIGURED",
                message="AI service is not configured",
                status_code=503,
            )

        if self._client is None:
            self._client = Groq(
                api_key=settings.GROQ_API_KEY,
                timeout=settings.GROQ_TIMEOUT_SECONDS,
                max_retries=settings.GROQ_MAX_RETRIES,
            )
            logger.info("Groq client initialised for model '%s'", self.model)

        return self._client

    def generate(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        json_mode: bool = False,
    ) -> GroqResult:
        """Send a chat completion request and return the generated text.

        Args:
            user_prompt: The task or question. Required.
            system_prompt: Role and constraints for the model. Optional here,
                but every agent in later phases will supply one.
            temperature: 0.0 is near-deterministic, higher is more varied.
            max_tokens: Upper bound on the length of the reply.
            json_mode: Ask the provider to constrain output to valid JSON.
                This makes malformed JSON much less likely but is not a
                guarantee — callers must still parse defensively.

        Raises:
            AppError: for every failure mode, already mapped to an HTTP
                status and a stable error code.
        """
        client = self._get_client()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # Log the shape of the request, never its content — prompts may carry
        # user data, and generated output can be large.
        logger.info(
            "Groq request: model=%s, messages=%d, prompt_chars=%d",
            self.model,
            len(messages),
            len(user_prompt),
        )

        # Only sent when requested — passing response_format unconditionally
        # would force JSON on every prose task.
        extra: dict[str, object] = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_completion_tokens=max_tokens,
                **extra,  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise self._to_app_error(exc) from exc

        return self._parse_response(response)

    def _parse_response(self, response: object) -> GroqResult:
        """Pull the generated text out of the SDK response object.

        Written defensively: a response with no choices is not an SDK crash,
        it just produces an empty string, which would silently become an
        empty article or empty code block downstream.
        """
        choices = getattr(response, "choices", None)
        if not choices:
            logger.error("Groq returned no choices")
            raise AppError(
                code="AI_EMPTY_RESPONSE",
                message="AI service returned an empty response",
                status_code=502,
            )

        content = getattr(choices[0].message, "content", None) or ""
        if not content.strip():
            logger.error("Groq returned empty content")
            raise AppError(
                code="AI_EMPTY_RESPONSE",
                message="AI service returned an empty response",
                status_code=502,
            )

        usage_obj = getattr(response, "usage", None)
        usage: dict[str, int] = {}
        if usage_obj is not None:
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage_obj, name, None)
                if isinstance(value, int):
                    usage[name] = value

        logger.info(
            "Groq response: chars=%d, tokens=%s",
            len(content),
            usage.get("total_tokens", "unknown"),
        )

        return GroqResult(
            content=content.strip(),
            model=getattr(response, "model", self.model),
            usage=usage,
        )

    def _to_app_error(self, exc: Exception) -> AppError:
        """Translate an SDK exception into our own error type.

        Ordering matters: APITimeoutError subclasses APIConnectionError, and
        RateLimitError subclasses APIStatusError, so the specific cases must
        be tested before the general ones.

        User-facing messages are our own words. The provider's text is only
        ever logged, and scrubbed first.
        """
        if isinstance(exc, AppError):
            return exc

        detail = _scrub(str(exc))

        if isinstance(exc, APITimeoutError):
            logger.error("Groq timeout after %ss", settings.GROQ_TIMEOUT_SECONDS)
            return AppError(
                code="AI_PROVIDER_TIMEOUT",
                message="AI service timed out. Please try again.",
                status_code=504,
            )

        if isinstance(exc, RateLimitError):
            logger.warning("Groq rate limit reached")
            return AppError(
                code="AI_RATE_LIMITED",
                message="AI service rate limit reached. Please try again shortly.",
                status_code=429,
            )

        if isinstance(exc, AuthenticationError):
            # Never say "your API key is wrong" to an end user — that is a
            # deployment problem, and the detail belongs in the server log.
            logger.error("Groq authentication failed - check GROQ_API_KEY")
            return AppError(
                code="AI_NOT_CONFIGURED",
                message="AI service is not configured",
                status_code=503,
            )

        if isinstance(exc, NotFoundError):
            logger.error(
                "Groq model '%s' not found - check GROQ_MODEL against "
                "https://console.groq.com/docs/models",
                self.model,
            )
            return AppError(
                code="AI_MODEL_UNAVAILABLE",
                message="The configured AI model is unavailable",
                status_code=503,
            )

        if isinstance(exc, BadRequestError):
            logger.error("Groq rejected the request: %s", detail)
            return AppError(
                code="AI_PROVIDER_ERROR",
                message="AI service could not process the request",
                status_code=502,
            )

        if isinstance(exc, (APIConnectionError, APIStatusError, GroqError)):
            logger.error("Groq API error (%s): %s", type(exc).__name__, detail)
            return AppError(
                code="AI_PROVIDER_ERROR",
                message="AI service is temporarily unavailable",
                status_code=502,
            )

        logger.error("Unexpected Groq failure (%s): %s", type(exc).__name__, detail)
        return AppError(
            code="AI_PROVIDER_ERROR",
            message="AI service is temporarily unavailable",
            status_code=502,
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool on shutdown."""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.info("Groq client closed")


# The single application-wide instance, mirroring the `mongodb` singleton.
groq_service = GroqService()
