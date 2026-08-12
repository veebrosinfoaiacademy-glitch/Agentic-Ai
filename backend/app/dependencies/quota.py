"""Quota enforcement for AI endpoints.

Applied to every route that spends provider budget, and to nothing else.
Health, registration, login, `/auth/me`, supported document types and document
upload are all free — none of them calls Groq.

**Where the reservation is spent, and why it works that way.**

FastAPI runs dependencies *before* it validates the request body: a request
with a malformed body still executes this dependency. Reserving here and
stopping there would therefore burn quota on requests that never reached an
agent, which is exactly what must not happen.

So the reservation is undone by `refund_unused_quota` in main.py whenever the
response is unsuccessful. A 422 refunds. A provider failure refunds. Only a
successful AI response keeps its claim.

Reserving up front rather than checking up front is deliberate: the increment
is atomic, so concurrent requests cannot both see the last remaining slot.
"""

import logging

from typing import Annotated

from fastapi import Depends, Request

from app.dependencies.auth import require_user
from app.schemas.auth_schemas import UserData
from app.services.usage_service import usage_service
from app.utils.errors import AppError

logger = logging.getLogger("app.usage")

# Read by the refund middleware. Set only when a claim actually needs undoing.
RESERVATION_ATTR = "usage_reservation_user_id"


def enforce_ai_quota(
    request: Request, user: UserData = Depends(require_user)
) -> UserData:
    """Claim one AI request for the signed-in user.

    Depends on `require_user`, so authentication is resolved first and an
    anonymous request is refused before any counter is touched — and long
    before the provider is reached.

    Identity comes from that dependency alone. No request body, query
    parameter or header can influence whose quota is spent.
    """
    reservation = usage_service.reserve(user.id)

    if not reservation.allowed:
        raise AppError(
            code="USAGE_LIMIT_EXCEEDED",
            message=(
                f"You have reached your {reservation.window.value}ly limit of "
                f"{reservation.limit} AI requests. Please try again later."
            ),
            status_code=429,
            details={
                "window": reservation.window.value,
                "limit": reservation.limit,
                "retry_after_seconds": reservation.retry_after_seconds,
            },
        )

    if reservation.recorded:
        # Marks this request as holding a claim that must be returned if the
        # response turns out to be unsuccessful.
        setattr(request.state, RESERVATION_ATTR, user.id)

    return user


# Mirrors `CurrentUser`, so a protected AI route reads
# `user: QuotaCheckedUser` and gets authentication plus quota in one place.
QuotaCheckedUser = Annotated[UserData, Depends(enforce_ai_quota)]
