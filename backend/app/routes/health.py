"""Health check endpoint.

Reports whether the API process is alive and whether its database is
reachable. Deliberately exposes no configuration values.
"""

from fastapi import APIRouter

from app.config import settings
from app.database import mongodb
from app.schemas.common_schemas import SuccessResponse, success

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=SuccessResponse,
    summary="Application health check",
)
def get_health() -> dict:
    """Return service and database status.

    The endpoint itself always returns HTTP 200 while the process is running —
    that is the point of a liveness check. Degraded dependencies are reported
    in the body via `data.status`, so a monitoring tool can distinguish
    "API is down" (no response) from "API is up, database is not" ("degraded").
    """
    # Ping live rather than trusting the startup result, so a cluster that
    # went down — or came back — is reflected immediately.
    mongodb.ping()
    database_status = mongodb.status()

    # Not configured is a valid state during early development, so it is not
    # degraded. Configured-but-unreachable is a real problem.
    is_degraded = bool(database_status["configured"]) and not database_status["connected"]

    return success(
        data={
            "status": "degraded" if is_degraded else "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "database": database_status,
        },
        message="API is degraded" if is_degraded else "API is healthy",
    )
