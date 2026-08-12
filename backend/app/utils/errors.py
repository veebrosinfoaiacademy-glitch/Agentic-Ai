"""Centralised error handling.

Two jobs:

1. Give the application its own exception type (`AppError`) so services and
   agents can fail with a meaningful error code instead of a bare Exception.
2. Register handlers on the FastAPI app so that *every* failure — expected or
   not — leaves the server in the same JSON shape defined in common_schemas.

The user never sees a Python traceback; the server log always does.
"""

import logging
import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common_schemas import error

logger = logging.getLogger("app")


class AppError(Exception):
    """An error we raised on purpose, with a code the frontend can branch on.

    Example:
        raise AppError("GROQ_UNAVAILABLE", "AI service is temporarily down", 503)
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: object = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


# Maps HTTP status codes to stable error codes, so a 404 always reports
# "NOT_FOUND" rather than whatever text the raiser happened to use.
_STATUS_CODE_NAMES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _code_for_status(status_code: int) -> str:
    return _STATUS_CODE_NAMES.get(status_code, "HTTP_ERROR")


def _retry_after_header(exc: AppError) -> dict[str, str] | None:
    """Standard `Retry-After` for a rate-limited response.

    Reads `retry_after_seconds` from the error's details when present. Putting
    it in a header rather than only in the body means generic HTTP clients and
    proxies can honour it without understanding our envelope.
    """
    if exc.status_code != 429 or not isinstance(exc.details, dict):
        return None
    seconds = exc.details.get("retry_after_seconds")
    if isinstance(seconds, int) and seconds > 0:
        return {"Retry-After": str(seconds)}
    return None


def _field_name(err: dict) -> str:
    """Name the field a validation error refers to.

    When the body is not valid JSON at all, Pydantic reports the location as
    a character offset, e.g. ("body", 103). Reporting `field: "103"` to a
    client is meaningless — there is no field 103 — so the whole body is
    named instead.
    """
    if err.get("type") == "json_invalid":
        return "body"
    return ".".join(str(part) for part in err.get("loc", []) if part != "body")


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all error handlers to the FastAPI application."""

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        """Errors we raised deliberately — safe to show the message."""
        logger.warning("AppError [%s]: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=error(code=exc.code, message=exc.message, details=exc.details),
            headers=_retry_after_header(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """FastAPI/Starlette HTTPExceptions, including automatic 404s."""
        message = str(exc.detail) if exc.detail else "Request failed"
        logger.warning("HTTPException %s: %s", exc.status_code, message)
        return JSONResponse(
            status_code=exc.status_code,
            content=error(code=_code_for_status(exc.status_code), message=message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic rejected the request body/query/path parameters.

        We reshape Pydantic's verbose error list into a short
        [{field, message}] list that is easy to render next to a form input.
        """
        details = [
            {"field": _field_name(err), "message": err.get("msg", "Invalid value")}
            for err in exc.errors()
        ]
        logger.warning("Validation failed: %s", details)
        return JSONResponse(
            # Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY to
            # ..._UNPROCESSABLE_CONTENT and deprecated the old name.
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error(
                code="VALIDATION_ERROR",
                message="Invalid request data",
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        """Anything we did not anticipate.

        The full traceback goes to the server log; the client gets a generic
        message. Leaking a traceback tells an attacker your file paths,
        package versions and code structure.
        """
        logger.error("Unhandled %s: %s", type(exc).__name__, exc)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error(
                code="INTERNAL_SERVER_ERROR",
                message="Internal server error",
            ),
        )
