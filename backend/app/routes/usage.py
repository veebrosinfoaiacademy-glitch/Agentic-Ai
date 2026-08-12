"""AI usage endpoint.

Reports the signed-in user's own consumption so a client can show a meter
before a request is refused. Read-only, and there is no way to ask about
anyone else: the user is taken from the token and the endpoint accepts no
parameters at all.

Deliberately NOT quota-checked — reading your remaining balance must keep
working after you have run out.
"""

from fastapi import APIRouter

from app.dependencies.auth import CurrentUser
from app.schemas.common_schemas import SuccessResponse, success
from app.services.usage_service import usage_service

router = APIRouter(tags=["Usage"])


@router.get(
    "",
    response_model=SuccessResponse,
    summary="Get your AI usage and limits",
    description=(
        "Current hourly and daily counts for the signed-in user, with the "
        "configured limits and when each window resets.\n\n"
        "A `limit` of 0 means that window is unlimited, and `remaining` is "
        "then null. Reading usage does not itself count against your quota."
    ),
)
def get_usage(user: CurrentUser) -> dict:
    usage = usage_service.get_usage(user_id=user.id)
    return success(
        data=usage.model_dump(mode="json"),
        message="Usage retrieved successfully",
    )
