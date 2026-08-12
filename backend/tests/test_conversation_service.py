"""Phase 11 tests: conversation persistence, ownership and agent routing.

Entirely offline — in-memory collections, no Atlas, no Groq.
"""

import pytest
from bson import ObjectId

from app.schemas.conversation_schemas import AgentType, MessageOptions, TaskType
from app.services.conversation_service import conversation_service
from app.utils.errors import AppError
from tests.conftest import FakeCollection, GenerateRecorder

USER_A = str(ObjectId())
USER_B = str(ObjectId())
DEFAULTS = MessageOptions()


def make_conversation(
    conversations: FakeCollection, user_id: str = USER_A, agent: str = "content"
) -> str:
    created = conversation_service.create(
        user_id=user_id, title="A conversation", agent_type=AgentType(agent)
    )
    return created.id


# --- Create -----------------------------------------------------------------


def test_create_stores_a_conversation_owned_by_the_caller(
    conversations: FakeCollection,
) -> None:
    created = conversation_service.create(USER_A, "My notes", AgentType.CONTENT)

    assert created.title == "My notes"
    assert created.agent_type == AgentType.CONTENT
    assert created.created_at is not None

    stored = conversations.documents[0]
    assert stored["user_id"] == ObjectId(USER_A)
    assert stored["title"] == "My notes"


def test_created_conversation_never_exposes_the_owner_id(
    conversations: FakeCollection,
) -> None:
    """The caller knows who they are; echoing an owner id invites misuse."""
    created = conversation_service.create(USER_A, "Notes", AgentType.CONTENT)

    assert "user_id" not in created.model_dump()


def test_create_reports_a_database_outage(
    failing_conversations: FakeCollection,
) -> None:
    with pytest.raises(AppError) as exc_info:
        conversation_service.create(USER_A, "Notes", AgentType.CONTENT)

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"
    assert exc_info.value.status_code == 503


# --- List -------------------------------------------------------------------


def test_list_returns_only_the_callers_conversations(
    conversations: FakeCollection,
) -> None:
    conversation_service.create(USER_A, "A one", AgentType.CONTENT)
    conversation_service.create(USER_A, "A two", AgentType.DEVELOPER)
    conversation_service.create(USER_B, "B one", AgentType.CONTENT)

    listing = conversation_service.list_for_user(USER_A, page=1, page_size=20)

    assert listing.total == 2
    assert {c.title for c in listing.conversations} == {"A one", "A two"}


def test_list_query_always_filters_by_owner(conversations: FakeCollection) -> None:
    """Ownership is part of the query, not a check on the result."""
    conversation_service.list_for_user(USER_A, page=1, page_size=20)

    assert conversations.queries
    for query in conversations.queries:
        assert query.get("user_id") == ObjectId(USER_A)


def test_list_sorts_most_recently_active_first(
    conversations: FakeCollection,
) -> None:
    from datetime import UTC, datetime

    conversation_service.create(USER_A, "older", AgentType.CONTENT)
    conversation_service.create(USER_A, "newer", AgentType.CONTENT)
    conversations.documents[0]["updated_at"] = datetime(2020, 1, 1, tzinfo=UTC)
    conversations.documents[1]["updated_at"] = datetime(2030, 1, 1, tzinfo=UTC)

    listing = conversation_service.list_for_user(USER_A, page=1, page_size=20)

    assert [c.title for c in listing.conversations] == ["newer", "older"]


def test_list_paginates(conversations: FakeCollection) -> None:
    for index in range(5):
        conversation_service.create(USER_A, f"conversation {index}", AgentType.CONTENT)

    first = conversation_service.list_for_user(USER_A, page=1, page_size=2)
    last = conversation_service.list_for_user(USER_A, page=3, page_size=2)

    assert first.total == 5
    assert len(first.conversations) == 2
    assert first.has_more is True
    assert last.has_more is False


def test_list_is_empty_for_a_new_user(conversations: FakeCollection) -> None:
    listing = conversation_service.list_for_user(USER_A, page=1, page_size=20)

    assert listing.conversations == []
    assert listing.total == 0
    assert listing.has_more is False


# --- Get --------------------------------------------------------------------


def test_get_returns_metadata_and_messages(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)
    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "Some source text.", DEFAULTS
    )

    detail = conversation_service.get_detail(USER_A, conversation_id)

    assert detail.id == conversation_id
    assert detail.message_count == 2
    assert [m.role.value for m in detail.messages] == ["user", "assistant"]


def test_messages_are_ordered_oldest_first(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)
    for text in ("first", "second", "third"):
        conversation_service.send_message(
            USER_A, conversation_id, TaskType.SUMMARIZE, text, DEFAULTS
        )

    detail = conversation_service.get_detail(USER_A, conversation_id)

    user_turns = [m.content for m in detail.messages if m.role.value == "user"]
    assert user_turns == ["first", "second", "third"]
    timestamps = [m.created_at for m in detail.messages]
    assert timestamps == sorted(timestamps)


# --- Rename -----------------------------------------------------------------


def test_rename_changes_only_the_title(conversations: FakeCollection) -> None:
    conversation_id = make_conversation(conversations)
    before = dict(conversations.documents[0])

    renamed = conversation_service.rename(USER_A, conversation_id, "Better title")

    after = conversations.documents[0]
    assert renamed.title == "Better title"
    assert after["user_id"] == before["user_id"]
    assert after["agent_type"] == before["agent_type"]
    assert after["created_at"] == before["created_at"]


# --- Delete -----------------------------------------------------------------


def test_delete_removes_the_conversation_and_its_messages(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)
    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
    )
    assert len(messages.documents) == 2

    conversation_service.delete(USER_A, conversation_id)

    assert conversations.documents == []
    assert messages.documents == []


def test_delete_leaves_other_conversations_intact(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    keep = make_conversation(conversations)
    remove = make_conversation(conversations)
    conversation_service.send_message(
        USER_A, keep, TaskType.SUMMARIZE, "keep me", DEFAULTS
    )

    conversation_service.delete(USER_A, remove)

    assert len(conversations.documents) == 1
    assert len(messages.documents) == 2


# --- Ownership: the core Phase 11 security requirement ----------------------


def test_user_b_cannot_read_user_a_conversation(
    conversations: FakeCollection, messages: FakeCollection
) -> None:
    conversation_id = make_conversation(conversations, user_id=USER_A)

    with pytest.raises(AppError) as exc_info:
        conversation_service.get_detail(USER_B, conversation_id)

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_user_b_cannot_rename_user_a_conversation(
    conversations: FakeCollection,
) -> None:
    conversation_id = make_conversation(conversations, user_id=USER_A)

    with pytest.raises(AppError) as exc_info:
        conversation_service.rename(USER_B, conversation_id, "hijacked")

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"
    assert conversations.documents[0]["title"] == "A conversation"


def test_user_b_cannot_delete_user_a_conversation(
    conversations: FakeCollection, messages: FakeCollection
) -> None:
    conversation_id = make_conversation(conversations, user_id=USER_A)

    with pytest.raises(AppError) as exc_info:
        conversation_service.delete(USER_B, conversation_id)

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"
    assert len(conversations.documents) == 1


def test_user_b_cannot_append_messages_to_user_a_conversation(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations, user_id=USER_A)

    with pytest.raises(AppError) as exc_info:
        conversation_service.send_message(
            USER_B, conversation_id, TaskType.SUMMARIZE, "intrusion", DEFAULTS
        )

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"
    assert messages.documents == []
    # Ownership is checked before the provider is ever called.
    assert recorded_generate.calls == []


def test_a_missing_conversation_and_someone_elses_are_indistinguishable(
    conversations: FakeCollection, messages: FakeCollection
) -> None:
    """Otherwise the endpoint becomes an oracle for which ids exist."""
    owned_by_a = make_conversation(conversations, user_id=USER_A)
    never_existed = str(ObjectId())

    with pytest.raises(AppError) as foreign:
        conversation_service.get_detail(USER_B, owned_by_a)
    with pytest.raises(AppError) as missing:
        conversation_service.get_detail(USER_B, never_existed)

    assert foreign.value.code == missing.value.code
    assert foreign.value.message == missing.value.message
    assert foreign.value.status_code == missing.value.status_code


@pytest.mark.parametrize(
    "operation",
    ["get", "rename", "delete", "message"],
)
def test_every_operation_scopes_its_query_by_owner(
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
    operation: str,
) -> None:
    """A structural check: no query reaches a conversation without user_id."""
    conversation_id = make_conversation(conversations, user_id=USER_A)
    conversations.queries.clear()

    actions = {
        "get": lambda: conversation_service.get_detail(USER_A, conversation_id),
        "rename": lambda: conversation_service.rename(USER_A, conversation_id, "new"),
        "delete": lambda: conversation_service.delete(USER_A, conversation_id),
        "message": lambda: conversation_service.send_message(
            USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
        ),
    }
    actions[operation]()

    assert conversations.queries
    for query in conversations.queries:
        assert "user_id" in query, f"{operation} issued an unscoped query: {query}"


# --- Invalid ids ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    ["not-an-objectid", "", "   ", "12345", "z" * 24, None],
    ids=["prose", "empty", "spaces", "short", "non-hex", "none"],
)
def test_malformed_conversation_id_is_a_clean_error(
    conversations: FakeCollection, messages: FakeCollection, bad_id
) -> None:
    """A bad id must never reach PyMongo and surface as a 500."""
    with pytest.raises(AppError) as exc_info:
        conversation_service.get_detail(USER_A, bad_id)

    assert exc_info.value.code == "INVALID_ID"
    assert exc_info.value.status_code == 422


def test_malformed_id_is_rejected_before_any_database_call(
    conversations: FakeCollection,
) -> None:
    with pytest.raises(AppError):
        conversation_service.rename(USER_A, "nonsense", "x")

    assert conversations.queries == []


# --- Messages ---------------------------------------------------------------


def test_both_turns_are_persisted(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    recorded_generate.content = "A concise summary."
    conversation_id = make_conversation(conversations)

    result = conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "Long article.", DEFAULTS
    )

    assert result.user_message.content == "Long article."
    assert result.user_message.role.value == "user"
    assert result.assistant_message.content == "A concise summary."
    assert result.assistant_message.role.value == "assistant"
    assert len(messages.documents) == 2


def test_messages_record_task_type_and_model(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)

    result = conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
    )

    assert result.user_message.task_type == TaskType.SUMMARIZE
    assert result.assistant_message.task_type == TaskType.SUMMARIZE
    assert result.assistant_message.model  # the model that actually answered
    assert result.user_message.model is None


def test_messages_carry_the_owner_for_defence_in_depth(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)

    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
    )

    for document in messages.documents:
        assert document["user_id"] == ObjectId(USER_A)
        assert document["conversation_id"] == ObjectId(conversation_id)


def test_sending_a_message_touches_updated_at(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)
    before = conversations.documents[0]["updated_at"]

    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
    )

    assert conversations.documents[0]["updated_at"] >= before


def test_structured_results_keep_their_payload(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    """A review's findings survive; `content` stays readable for the transcript."""
    import json

    recorded_generate.content = json.dumps(
        {
            "overall_assessment": "Needs input validation.",
            "issues": [{"severity": "high", "problem": "No bounds check."}],
        }
    )
    conversation_id = make_conversation(conversations, agent="developer")

    result = conversation_service.send_message(
        USER_A, conversation_id, TaskType.REVIEW, "def f(x): return x[0]", DEFAULTS
    )

    assert result.assistant_message.content == "Needs input validation."
    assert result.assistant_message.data["issues"][0]["severity"] == "high"


# --- AI failure -------------------------------------------------------------


def test_provider_failure_records_no_assistant_message(
    conversations: FakeCollection, messages: FakeCollection, failing_generate
) -> None:
    """Nothing is fabricated when the provider fails."""
    conversation_id = make_conversation(conversations)

    with pytest.raises(AppError) as exc_info:
        conversation_service.send_message(
            USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
        )

    assert exc_info.value.code == "AI_PROVIDER_ERROR"
    roles = [d["role"] for d in messages.documents]
    assert roles == ["user"]  # the user's own words are kept; no fake reply


def test_provider_failure_leaves_the_users_message_intact(
    conversations: FakeCollection, messages: FakeCollection, failing_generate
) -> None:
    """Deliberate: a chat that discards your input on a provider hiccup is
    worse than one showing an unanswered turn."""
    conversation_id = make_conversation(conversations)

    with pytest.raises(AppError):
        conversation_service.send_message(
            USER_A, conversation_id, TaskType.SUMMARIZE, "my typed prompt", DEFAULTS
        )

    assert messages.documents[0]["content"] == "my typed prompt"


# --- Agent routing ----------------------------------------------------------


def test_content_conversation_reaches_the_content_agent(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    from app.prompts import content_prompts

    conversation_id = make_conversation(conversations, agent="content")

    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "Some text.", DEFAULTS
    )

    assert recorded_generate.system_prompt == content_prompts.SUMMARIZATION_PROMPT


def test_developer_conversation_reaches_the_developer_agent(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    from app.prompts import developer_prompts

    recorded_generate.content = '{"summary": "It adds numbers."}'
    conversation_id = make_conversation(conversations, agent="developer")

    conversation_service.send_message(
        USER_A, conversation_id, TaskType.EXPLAIN, "def add(a,b): return a+b", DEFAULTS
    )

    assert recorded_generate.system_prompt == developer_prompts.CODE_EXPLANATION_PROMPT


@pytest.mark.parametrize(
    ("agent", "task"),
    [
        ("content", TaskType.EXPLAIN),
        ("content", TaskType.REVIEW),
        ("content", TaskType.DEBUG),
        ("developer", TaskType.SUMMARIZE),
        ("developer", TaskType.TONE),
        ("developer", TaskType.EXTRACT),
    ],
)
def test_a_task_the_agent_cannot_perform_is_rejected(
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
    agent: str,
    task: TaskType,
) -> None:
    """The wrong agent must never silently run the task."""
    conversation_id = make_conversation(conversations, agent=agent)

    with pytest.raises(AppError) as exc_info:
        conversation_service.send_message(
            USER_A, conversation_id, task, "input", DEFAULTS
        )

    assert exc_info.value.code == "TASK_NOT_SUPPORTED"
    assert exc_info.value.status_code == 422
    assert recorded_generate.calls == []
    assert messages.documents == []


def test_generate_is_routed_by_the_conversations_agent(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    """"generate" exists in both agents; agent_type disambiguates it."""
    from app.prompts import content_prompts, developer_prompts

    content_id = make_conversation(conversations, agent="content")
    developer_id = make_conversation(conversations, agent="developer")

    conversation_service.send_message(
        USER_A, content_id, TaskType.GENERATE, "AI in education", DEFAULTS
    )
    assert recorded_generate.system_prompt == content_prompts.CONTENT_GENERATION_PROMPT

    recorded_generate.content = '{"code": "print(1)"}'
    conversation_service.send_message(
        USER_A, developer_id, TaskType.GENERATE, "print one", DEFAULTS
    )
    assert recorded_generate.system_prompt == developer_prompts.CODE_GENERATION_PROMPT


def test_rewrite_requires_instructions(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations, agent="content")

    with pytest.raises(AppError) as exc_info:
        conversation_service.send_message(
            USER_A, conversation_id, TaskType.REWRITE, "text", MessageOptions()
        )

    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.details[0]["field"] == "options.instructions"


def test_options_are_forwarded_to_the_agent(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    from app.prompts.content_prompts import TONE_GUIDANCE
    from app.schemas.content_schemas import Tone

    conversation_id = make_conversation(conversations, agent="content")

    conversation_service.send_message(
        USER_A,
        conversation_id,
        TaskType.TONE,
        "Pursuant to our correspondence…",
        MessageOptions(tone=Tone.CASUAL),
    )

    assert TONE_GUIDANCE[Tone.CASUAL] in recorded_generate.user_prompt


# --- Database failures ------------------------------------------------------


def test_message_insert_failure_is_reported_cleanly(
    conversations: FakeCollection, monkeypatch: pytest.MonkeyPatch, recorded_generate
) -> None:
    """Never claim a message was stored when the write failed."""
    conversation_id = make_conversation(conversations)
    broken = FakeCollection(fail=True)
    monkeypatch.setattr(
        "app.services.conversation_service.get_messages_collection", lambda: broken
    )

    with pytest.raises(AppError) as exc_info:
        conversation_service.send_message(
            USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
        )

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"


def test_message_retrieval_failure_is_reported_cleanly(
    conversations: FakeCollection, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation_id = make_conversation(conversations)
    broken = FakeCollection(fail=True)
    monkeypatch.setattr(
        "app.services.conversation_service.get_messages_collection", lambda: broken
    )

    with pytest.raises(AppError) as exc_info:
        conversation_service.get_detail(USER_A, conversation_id)

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"


@pytest.mark.parametrize("operation", ["list", "get", "rename", "delete"])
def test_database_outage_never_leaks_pymongo_details(
    failing_conversations: FakeCollection, operation: str
) -> None:
    valid_id = str(ObjectId())
    actions = {
        "list": lambda: conversation_service.list_for_user(USER_A, 1, 20),
        "get": lambda: conversation_service.get_detail(USER_A, valid_id),
        "rename": lambda: conversation_service.rename(USER_A, valid_id, "x"),
        "delete": lambda: conversation_service.delete(USER_A, valid_id),
    }

    with pytest.raises(AppError) as exc_info:
        actions[operation]()

    message = exc_info.value.message
    assert exc_info.value.code == "DATABASE_UNAVAILABLE"
    for leak in ("pymongo", "ServerSelection", "mongodb", "Traceback", "27017"):
        assert leak.lower() not in message.lower()


# --- Nothing sensitive is stored --------------------------------------------


def test_stored_documents_contain_no_credentials(
    conversations: FakeCollection,
    messages: FakeCollection,
    recorded_generate,
    jwt_secret: str,
) -> None:
    conversation_id = make_conversation(conversations)
    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
    )

    stored = str(conversations.documents) + str(messages.documents)
    for forbidden in ("password", "password_hash", "authorization", "bearer", "eyJ",
                      "gsk_", "mongodb+srv", jwt_secret):
        assert forbidden.lower() not in stored.lower()


def test_message_documents_hold_only_expected_fields(
    conversations: FakeCollection, messages: FakeCollection, recorded_generate
) -> None:
    conversation_id = make_conversation(conversations)
    conversation_service.send_message(
        USER_A, conversation_id, TaskType.SUMMARIZE, "text", DEFAULTS
    )

    assert set(messages.documents[0]) == {
        "_id", "conversation_id", "user_id", "role", "content", "task_type",
        "model", "created_at",
    }
    assert set(messages.documents[1]) == {
        "_id", "conversation_id", "user_id", "role", "content", "task_type",
        "model", "created_at", "data",
    }
