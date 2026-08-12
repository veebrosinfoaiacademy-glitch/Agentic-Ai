"""Conversation history endpoints.

Thin: authenticate, validate, call the service, wrap the result. Ownership
filtering, agent routing and persistence all live in the service.

Every route here is protected. The caller's identity comes from the JWT via
`CurrentUser` — no endpoint accepts a user id, and none of the URLs can be
used to reach another account's data.
"""

from fastapi import APIRouter, Query, status

from app.dependencies.auth import CurrentUser
from app.schemas.common_schemas import SuccessResponse, success
from app.schemas.conversation_schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CreateConversationRequest,
    RenameConversationRequest,
    SendMessageRequest,
)
from app.services.conversation_service import conversation_service

router = APIRouter(tags=["Conversations"])

_NOT_FOUND = {
    "description": "No such conversation, or it belongs to another user",
}


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation",
    description=(
        "Starts a conversation owned by the signed-in user. `agent_type` "
        "fixes which agent the conversation talks to and cannot be changed "
        "afterwards."
    ),
)
def create_conversation(request: CreateConversationRequest, user: CurrentUser) -> dict:
    conversation = conversation_service.create(
        user_id=user.id, title=request.title, agent_type=request.agent_type
    )
    return success(
        data=conversation.model_dump(mode="json"),
        message="Conversation created successfully",
    )


@router.get(
    "",
    response_model=SuccessResponse,
    summary="List your conversations",
    description=(
        "Returns only the signed-in user's conversations, most recently "
        "active first. Messages are not included — fetch a single "
        "conversation for its transcript."
    ),
)
def list_conversations(
    user: CurrentUser,
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Conversations per page (max {MAX_PAGE_SIZE}).",
    ),
) -> dict:
    listing = conversation_service.list_for_user(
        user_id=user.id, page=page, page_size=page_size
    )
    return success(
        data=listing.model_dump(mode="json"),
        message="Conversations retrieved successfully",
    )


@router.get(
    "/{conversation_id}",
    response_model=SuccessResponse,
    summary="Get a conversation and its messages",
    description="Messages are ordered oldest first.",
    responses={404: _NOT_FOUND},
)
def get_conversation(conversation_id: str, user: CurrentUser) -> dict:
    detail = conversation_service.get_detail(
        user_id=user.id, conversation_id=conversation_id
    )
    return success(
        data=detail.model_dump(mode="json"),
        message="Conversation retrieved successfully",
    )


@router.patch(
    "/{conversation_id}",
    response_model=SuccessResponse,
    summary="Rename a conversation",
    description="Title is the only field that can be changed.",
    responses={404: _NOT_FOUND},
)
def rename_conversation(
    conversation_id: str, request: RenameConversationRequest, user: CurrentUser
) -> dict:
    conversation = conversation_service.rename(
        user_id=user.id, conversation_id=conversation_id, title=request.title
    )
    return success(
        data=conversation.model_dump(mode="json"),
        message="Conversation renamed successfully",
    )


@router.delete(
    "/{conversation_id}",
    response_model=SuccessResponse,
    summary="Delete a conversation",
    description="Removes the conversation and every message in it.",
    responses={404: _NOT_FOUND},
)
def delete_conversation(conversation_id: str, user: CurrentUser) -> dict:
    conversation_service.delete(user_id=user.id, conversation_id=conversation_id)
    return success(data=None, message="Conversation deleted successfully")


@router.post(
    "/{conversation_id}/messages",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message and get the agent's reply",
    description=(
        "Runs one agent task inside the conversation and records both turns.\n\n"
        "`task_type` must be one the conversation's agent supports — a "
        "developer task in a content conversation is rejected rather than "
        "silently run by the wrong agent.\n\n"
        "`options` is optional; every field defaults to the same value the "
        "matching direct endpoint uses."
    ),
    responses={
        404: _NOT_FOUND,
        422: {"description": "Invalid input, or a task the agent cannot perform"},
        502: {"description": "The AI provider failed; no reply was recorded"},
    },
)
def send_message(
    conversation_id: str, request: SendMessageRequest, user: CurrentUser
) -> dict:
    result = conversation_service.send_message(
        user_id=user.id,
        conversation_id=conversation_id,
        task_type=request.task_type,
        prompt=request.prompt,
        options=request.options,
    )
    return success(
        data=result.model_dump(mode="json"), message="Message sent successfully"
    )
