"""Response envelopes shared by every endpoint in the API.

Having one success shape and one error shape means the React frontend can
write a single response handler instead of special-casing each endpoint.
"""

from typing import Any

from pydantic import BaseModel, Field


class SuccessResponse(BaseModel):
    """Standard wrapper for a successful request."""

    success: bool = True
    message: str = "Request successful"
    data: Any | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Request successful",
                "data": {},
            }
        }
    }


class ErrorDetail(BaseModel):
    """Machine-readable part of an error response."""

    code: str = Field(description="Stable error code, e.g. VALIDATION_ERROR")
    details: Any | None = Field(
        default=None, description="Optional structured context about the failure"
    )


class ErrorResponse(BaseModel):
    """Standard wrapper for a failed request."""

    success: bool = False
    message: str = "Something went wrong"
    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": False,
                "message": "Internal server error",
                "error": {"code": "INTERNAL_SERVER_ERROR", "details": None},
            }
        }
    }


class DatabaseStatus(BaseModel):
    """Database connectivity reported by the health endpoint.

    Booleans only. Nothing here may ever carry a URI, host, username or
    password — this payload is public to anyone who can reach /api/health.
    """

    configured: bool = Field(description="Whether MONGODB_URI is set")
    connected: bool = Field(description="Whether the last ping succeeded")
    type: str = Field(default="mongodb", description="Database engine")


class HealthData(BaseModel):
    """Payload returned inside the health endpoint's `data` field."""

    status: str = Field(description='"ok" when healthy, "degraded" otherwise')
    service: str
    version: str
    database: DatabaseStatus


def success(data: Any = None, message: str = "Request successful") -> dict[str, Any]:
    """Build a success envelope as a plain dict.

    Routes return this so they never have to repeat the
    `{"success": ..., "message": ..., "data": ...}` boilerplate.
    """
    return {"success": True, "message": message, "data": data}


def error(
    code: str,
    message: str = "Something went wrong",
    details: Any = None,
) -> dict[str, Any]:
    """Build an error envelope as a plain dict."""
    return {
        "success": False,
        "message": message,
        "error": {"code": code, "details": details},
    }
