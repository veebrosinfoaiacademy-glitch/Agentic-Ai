"""Conversation persistence and message orchestration.

Two responsibilities:

* CRUD over the caller's own conversations, where "own" is enforced by the
  database query rather than by a check afterwards;
* running one agent task and recording both turns.

It orchestrates the existing agents — it does not reimplement them. No Groq
call, no prompt, no JSON parsing and no output validation lives here.
"""

import logging
from datetime import UTC, datetime
from typing import Callable

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from app.agents.content_agent import content_agent
from app.agents.developer_agent import developer_agent
from app.database import get_conversations_collection, get_messages_collection
from app.schemas.conversation_schemas import (
    TASKS_BY_AGENT,
    AgentType,
    ConversationData,
    ConversationDetailData,
    ConversationListData,
    MessageData,
    MessageOptions,
    MessageRole,
    SendMessageData,
    TaskType,
)
from app.utils.errors import AppError

logger = logging.getLogger("app.conversations")

# A transcript line for a structured result. The full payload is kept in the
# message's `data` field; this is what a chat view renders.
_MAX_TRANSCRIPT_CHARS = 4_000


def _now() -> datetime:
    """UTC-aware, matching the timestamps auth_service already writes."""
    return datetime.now(UTC)


def _database_unavailable(exc: PyMongoError) -> AppError:
    """MongoDB could not answer.

    Never claims a write succeeded when it did not, and never surfaces the
    PyMongo message, which carries cluster hostnames.
    """
    logger.error("Conversation database operation failed: %s", type(exc).__name__)
    return AppError(
        code="DATABASE_UNAVAILABLE",
        message="The service is temporarily unavailable. Please try again.",
        status_code=503,
    )


def _not_found() -> AppError:
    """The conversation does not exist, or belongs to someone else.

    Deliberately one error for both. Distinguishing them would turn this
    endpoint into an oracle for "which conversation ids exist", so a caller
    asking about someone else's conversation gets exactly what they would get
    for an id that was never issued.

    404 rather than 403 for the same reason: 403 would confirm the resource
    is real.
    """
    return AppError(
        code="CONVERSATION_NOT_FOUND",
        message="Conversation not found",
        status_code=404,
    )


def _to_object_id(value: str, label: str) -> ObjectId:
    """Parse an id from a URL, failing cleanly rather than with a 500.

    ObjectId(None) silently generates a new random id instead of raising, so
    the type check has to come first.
    """
    if not isinstance(value, str) or not value.strip():
        raise AppError(
            code="INVALID_ID",
            message=f"Invalid {label} id",
            status_code=422,
        )
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        logger.info("Rejected malformed %s id", label)
        raise AppError(
            code="INVALID_ID",
            message=f"Invalid {label} id",
            status_code=422,
        ) from None


def _to_conversation(document: dict, message_count: int = 0) -> ConversationData:
    """Convert a stored document into its public form.

    Fields are named explicitly rather than filtered out, so a field added to
    the document later cannot leak by omission. `user_id` never crosses this
    boundary.
    """
    return ConversationData(
        id=str(document["_id"]),
        title=document["title"],
        agent_type=document["agent_type"],
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        message_count=message_count,
    )


def _to_message(document: dict) -> MessageData:
    return MessageData(
        id=str(document["_id"]),
        role=document["role"],
        content=document["content"],
        task_type=document.get("task_type"),
        model=document.get("model"),
        created_at=document["created_at"],
        data=document.get("data"),
    )


# --- Agent routing ----------------------------------------------------------
#
# One table mapping (agent, task) to a call on the existing agent. Adding a
# task later means one row here, not a new branch in the request handler.


def _content_call(task: TaskType, prompt: str, options: MessageOptions):
    agent = content_agent
    match task:
        case TaskType.GENERATE:
            return agent.generate(
                topic=prompt,
                content_type=options.content_type,
                tone=options.tone,
                audience=options.audience,
                length=options.length,
                additional_instructions=options.instructions,
            )
        case TaskType.SUMMARIZE:
            return agent.summarize(text=prompt, summary_type=options.summary_type)
        case TaskType.REWRITE:
            if not options.instructions:
                raise AppError(
                    code="VALIDATION_ERROR",
                    message="The rewrite task needs options.instructions",
                    status_code=422,
                    details=[
                        {
                            "field": "options.instructions",
                            "message": "Describe how the text should be rewritten",
                        }
                    ],
                )
            return agent.rewrite(text=prompt, instructions=options.instructions)
        case TaskType.TONE:
            return agent.transform_tone(text=prompt, tone=options.tone)
        case TaskType.AUDIENCE:
            return agent.adapt_audience(text=prompt, audience=options.audience)
        case TaskType.FORMAT:
            return agent.transform_format(
                text=prompt, content_format=options.content_format
            )
        case TaskType.EXTRACT:
            return agent.extract_information(text=prompt)
    raise AssertionError(f"unrouted content task: {task}")


def _developer_call(task: TaskType, prompt: str, options: MessageOptions):
    agent = developer_agent
    language = options.language
    match task:
        case TaskType.GENERATE:
            return agent.generate_code(
                language=language, description=prompt, requirements=options.requirements
            )
        case TaskType.EXPLAIN:
            return agent.explain_code(language=language, code=prompt)
        case TaskType.REVIEW:
            return agent.review_code(
                language=language, code=prompt, review_focus=options.review_focus
            )
        case TaskType.REFACTOR:
            return agent.refactor_code(
                language=language, code=prompt, goals=options.goals
            )
        case TaskType.TESTS:
            return agent.generate_tests(
                language=language, code=prompt, framework=options.framework
            )
        case TaskType.DEBUG:
            return agent.analyse_bug(
                language=language,
                code=prompt,
                error_message=options.error_message,
                context=options.context,
            )
        case TaskType.DOCUMENT:
            return agent.generate_documentation(
                language=language,
                code=prompt,
                documentation_type=options.documentation_type,
            )
    raise AssertionError(f"unrouted developer task: {task}")


AGENT_DISPATCH: dict[AgentType, Callable] = {
    AgentType.CONTENT: _content_call,
    AgentType.DEVELOPER: _developer_call,
}


def _transcript_text(result: object) -> str:
    """A readable line for the chat view.

    Text tasks already produce prose. Structured tasks (a review, an
    extraction) produce a dict, which reads badly in a transcript, so this
    picks the most meaningful human summary. The full structure is stored
    alongside in `data` and rendered by the existing result components.
    """
    content = getattr(result, "content", "") or ""
    data = getattr(result, "data", None)

    if isinstance(data, dict) and data:
        for key in (
            "summary", "overall_assessment", "explanation", "problem",
            "original_intent", "coverage_notes", "code",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:_MAX_TRANSCRIPT_CHARS]

    if content.strip():
        return content.strip()[:_MAX_TRANSCRIPT_CHARS]

    return "(the agent returned no readable text)"


def _structured_payload(result: object) -> dict | None:
    """The structured half of an agent result, if it produced one."""
    data = getattr(result, "data", None)
    if isinstance(data, dict) and data:
        return data
    structured = getattr(result, "structured", None)
    if isinstance(structured, dict) and structured:
        return structured
    return None


class ConversationService:
    """Owns conversations and their messages, scoped to one user."""

    # --- Ownership ----------------------------------------------------------

    @staticmethod
    def _owned(conversation_id: ObjectId, user_id: ObjectId) -> dict:
        """The only filter used to reach a conversation.

        Ownership is part of the query, not a check performed on the result.
        A `find_one({"_id": ...})` followed by an `if` is one forgotten
        branch away from an IDOR; this cannot return another user's row at all.
        """
        return {"_id": conversation_id, "user_id": user_id}

    def _load_owned(self, conversation_id: str, user_id: str) -> dict:
        """Fetch a conversation the caller owns, or raise 404."""
        oid = _to_object_id(conversation_id, "conversation")
        owner = _to_object_id(user_id, "user")

        try:
            document = get_conversations_collection().find_one(self._owned(oid, owner))
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        if document is None:
            logger.info("Conversation lookup miss or not owned by the caller")
            raise _not_found()
        return document

    # --- CRUD ---------------------------------------------------------------

    def create(self, user_id: str, title: str, agent_type: AgentType) -> ConversationData:
        """Start a new conversation owned by the authenticated user."""
        owner = _to_object_id(user_id, "user")
        now = _now()
        document = {
            "user_id": owner,
            "title": title,
            "agent_type": agent_type.value,
            "created_at": now,
            "updated_at": now,
        }

        try:
            result = get_conversations_collection().insert_one(document)
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        document["_id"] = result.inserted_id
        logger.info("Conversation %s created for user %s", result.inserted_id, owner)
        return _to_conversation(document)

    def list_for_user(
        self, user_id: str, page: int, page_size: int
    ) -> ConversationListData:
        """One page of the caller's conversations, most recently active first."""
        owner = _to_object_id(user_id, "user")
        conversations = get_conversations_collection()
        query = {"user_id": owner}

        try:
            total = conversations.count_documents(query)
            cursor = (
                conversations.find(query)
                .sort("updated_at", -1)
                .skip((page - 1) * page_size)
                .limit(page_size)
            )
            documents = list(cursor)
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        return ConversationListData(
            conversations=[_to_conversation(doc) for doc in documents],
            page=page,
            page_size=page_size,
            total=total,
            has_more=(page * page_size) < total,
        )

    def get_detail(self, user_id: str, conversation_id: str) -> ConversationDetailData:
        """A conversation plus its transcript, oldest message first."""
        document = self._load_owned(conversation_id, user_id)

        try:
            messages = list(
                get_messages_collection()
                .find({"conversation_id": document["_id"], "user_id": document["user_id"]})
                .sort("created_at", 1)
            )
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        base = _to_conversation(document, message_count=len(messages))
        return ConversationDetailData(
            **base.model_dump(),
            messages=[_to_message(message) for message in messages],
        )

    def rename(self, user_id: str, conversation_id: str, title: str) -> ConversationData:
        """Change a conversation's title. Nothing else is mutable."""
        oid = _to_object_id(conversation_id, "conversation")
        owner = _to_object_id(user_id, "user")

        try:
            document = get_conversations_collection().find_one_and_update(
                self._owned(oid, owner),
                # An explicit field list, so a crafted request cannot reach
                # user_id, agent_type or created_at.
                {"$set": {"title": title, "updated_at": _now()}},
                return_document=True,
            )
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        if document is None:
            raise _not_found()

        logger.info("Conversation %s renamed", oid)
        return _to_conversation(document)

    def delete(self, user_id: str, conversation_id: str) -> None:
        """Delete a conversation and its messages.

        The conversation goes first: if the message delete then fails, the
        conversation is already unreachable, so no transcript is exposed. The
        reverse order could leave a readable conversation with its messages
        removed, which is worse.
        """
        oid = _to_object_id(conversation_id, "conversation")
        owner = _to_object_id(user_id, "user")

        try:
            result = get_conversations_collection().delete_one(self._owned(oid, owner))
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        if result.deleted_count == 0:
            raise _not_found()

        try:
            removed = get_messages_collection().delete_many(
                {"conversation_id": oid, "user_id": owner}
            )
            logger.info(
                "Conversation %s deleted with %d message(s)", oid, removed.deleted_count
            )
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

    # --- Messages -----------------------------------------------------------

    def send_message(
        self,
        user_id: str,
        conversation_id: str,
        task_type: TaskType,
        prompt: str,
        options: MessageOptions,
    ) -> SendMessageData:
        """Run one agent task inside a conversation and record both turns.

        Order matters, and is deliberate:

        1. verify ownership — before any provider spend;
        2. reject a task the conversation's agent cannot perform;
        3. persist the user's message;
        4. call the existing agent;
        5. persist the assistant reply only if step 4 succeeded.

        On an AI failure the user's message is kept. It is something the
        person actually wrote, and a chat that silently discards your input
        when the provider is busy is worse than one showing an unanswered
        turn. Nothing is fabricated in its place, which is the rule that
        matters.
        """
        conversation = self._load_owned(conversation_id, user_id)
        agent_type = AgentType(conversation["agent_type"])

        if task_type not in TASKS_BY_AGENT[agent_type]:
            allowed = ", ".join(sorted(t.value for t in TASKS_BY_AGENT[agent_type]))
            raise AppError(
                code="TASK_NOT_SUPPORTED",
                message=(
                    f"'{task_type.value}' is not a {agent_type.value} task. "
                    f"This conversation supports: {allowed}"
                ),
                status_code=422,
            )

        messages = get_messages_collection()
        owner = conversation["user_id"]
        oid = conversation["_id"]

        user_document = {
            "conversation_id": oid,
            "user_id": owner,
            "role": MessageRole.USER.value,
            "content": prompt,
            "task_type": task_type.value,
            "model": None,
            "created_at": _now(),
        }
        try:
            user_document["_id"] = messages.insert_one(user_document).inserted_id
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        # Errors from the agent (provider failures, invalid model output) are
        # already AppErrors and propagate untouched. No assistant message is
        # written, and the caller sees the existing provider error envelope.
        result = AGENT_DISPATCH[agent_type](task_type, prompt, options)

        assistant_document = {
            "conversation_id": oid,
            "user_id": owner,
            "role": MessageRole.ASSISTANT.value,
            "content": _transcript_text(result),
            "task_type": task_type.value,
            "model": getattr(result, "model", None),
            "created_at": _now(),
            "data": _structured_payload(result),
        }
        try:
            assistant_document["_id"] = messages.insert_one(
                assistant_document
            ).inserted_id
            get_conversations_collection().update_one(
                self._owned(oid, owner), {"$set": {"updated_at": _now()}}
            )
        except PyMongoError as exc:
            raise _database_unavailable(exc) from None

        logger.info("Conversation %s: %s turn recorded", oid, task_type.value)

        return SendMessageData(
            conversation_id=str(oid),
            user_message=_to_message(user_document),
            assistant_message=_to_message(assistant_document),
        )


conversation_service = ConversationService()
