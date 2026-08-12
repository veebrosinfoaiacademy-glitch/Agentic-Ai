"""Temporary endpoint for verifying the Groq integration.

Phase 5 replaces this with real Content Agent routes. It stays deliberately
thin: validate input, call the service, wrap the result. No prompt building,
no SDK calls, no database writes.
"""

import logging

from fastapi import APIRouter

from app.dependencies.quota import QuotaCheckedUser
from app.schemas.ai_schemas import AITestRequest
from app.schemas.common_schemas import SuccessResponse, success
from app.services.groq_service import groq_service

logger = logging.getLogger("app.routes.ai")

router = APIRouter(tags=["AI"])


@router.post(
    "/test",
    response_model=SuccessResponse,
    summary="Send a prompt to Groq (integration check)",
    description=(
        "Verifies that FastAPI can reach the Groq API. The API key is read "
        "from the server environment and is never accepted from the client."
    ),
)
def test_ai(request: AITestRequest, user: QuotaCheckedUser) -> dict:
    """Send the prompt to Groq and return the generated text.

    Failures raise AppError inside the service and are converted to the
    standard error envelope by the Phase 2 handlers — there is no try/except
    here on purpose.
    """
    logger.info("AI test request received (%d chars)", len(request.prompt))

    result = groq_service.generate(
        user_prompt=request.prompt,
        system_prompt="You are a helpful assistant. Answer clearly and concisely.",
    )

    return success(
        data={
            "content": result.content,
            "model": result.model,
            "usage": result.usage,
        },
        message="AI request completed",
    )
