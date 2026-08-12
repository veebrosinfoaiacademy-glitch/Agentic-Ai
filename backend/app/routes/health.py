"""Health check endpoint.

Phase 2 reports only that the API process is alive. Phase 3 extends this to
also report MongoDB connectivity.
"""

from fastapi import APIRouter

from app.config import settings
from app.schemas.common_schemas import SuccessResponse, success

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=SuccessResponse,
    summary="Application health check",
)
def get_health() -> dict:
    """Return basic service information.

    Deliberately exposes nothing sensitive: no API keys, no connection
    strings, no environment dump.
    """
    return success(
        data={
            "status": "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
        },
        message="API is healthy",
    )
