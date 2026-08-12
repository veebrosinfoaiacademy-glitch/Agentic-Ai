"""Schemas for conversations and messages.

Two things worth noting before reading on.

First, no request model here has a `user_id`, `owner_id` or any other
identity field. Ownership comes from the JWT and nowhere else, so there is
no code path through which a client could claim to be someone else. A test
asserts this structurally across every request schema in the application.

Second, the task vocabularies are imported from the Content and Developer
agent schemas rather than redefined. A second copy of "the tones we support"
would drift from the first the moment either changed.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.content_schemas import (
    Audience,
    ContentFormat,
    ContentLength,
    ContentType,
    SummaryType,
    Tone,
)
from app.schemas.developer_schemas import (
    MAX_LIST_ITEM_CHARS,
    MAX_LIST_ITEMS,
    DocumentationType,
    LanguageName,
    ReviewFocus,
)

# A title is a label, not content. 200 characters is generous for one.
MAX_TITLE_CHARS = 200

# The prompt carries whatever the task needs — a topic, an article to
# summarise, or a source file to review. It matches the Developer Agent's
# code ceiling so a conversation can handle anything the direct endpoints can.
MAX_PROMPT_CHARS = 30_000

MAX_INSTRUCTION_CHARS = 1_000

# Pagination bounds. 100 is the most a single page may request; beyond that
# the client should paginate rather than pull an unbounded history.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

TitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS),
]
PromptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT_CHARS),
]
InstructionText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_INSTRUCTION_CHARS
    ),
]
ListItemText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_LIST_ITEM_CHARS
    ),
]


class AgentType(str, Enum):
    """Which agent a conversation belongs to."""

    CONTENT = "content"
    DEVELOPER = "developer"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class TaskType(str, Enum):
    """Tasks a conversation message can request.

    Named after the existing REST routes, so `/api/content/summarize` and
    `task_type: "summarize"` are obviously the same operation.

    "generate" appears in both agents. That is not ambiguous here because the
    conversation's `agent_type` disambiguates it — the service looks tasks up
    by (agent_type, task), so a developer conversation asking to "generate"
    reaches the code generator and a content one reaches the writer.
    """

    # Content agent
    GENERATE = "generate"
    SUMMARIZE = "summarize"
    REWRITE = "rewrite"
    TONE = "tone"
    AUDIENCE = "audience"
    FORMAT = "format"
    EXTRACT = "extract"

    # Developer agent (GENERATE is shared)
    EXPLAIN = "explain"
    REVIEW = "review"
    REFACTOR = "refactor"
    TESTS = "tests"
    DEBUG = "debug"
    DOCUMENT = "document"


# Which tasks each agent can actually perform. The service uses this to reject
# a developer task sent to a content conversation, and vice versa.
TASKS_BY_AGENT: dict[AgentType, set[TaskType]] = {
    AgentType.CONTENT: {
        TaskType.GENERATE,
        TaskType.SUMMARIZE,
        TaskType.REWRITE,
        TaskType.TONE,
        TaskType.AUDIENCE,
        TaskType.FORMAT,
        TaskType.EXTRACT,
    },
    AgentType.DEVELOPER: {
        TaskType.GENERATE,
        TaskType.EXPLAIN,
        TaskType.REVIEW,
        TaskType.REFACTOR,
        TaskType.TESTS,
        TaskType.DEBUG,
        TaskType.DOCUMENT,
    },
}


class MessageOptions(BaseModel):
    """Task-specific settings, all optional.

    `{task_type, prompt}` alone is always a valid request — every field here
    has a default matching the direct endpoint's default. These exist so a
    conversation can express "rewrite this *formally*" or "review this *Go*
    code", which the two-field request could not.

    Types are the agents' own enums, so an unsupported tone is rejected here
    exactly as it would be at /api/content/tone.
    """

    # Content
    content_type: ContentType = ContentType.BLOG
    tone: Tone = Tone.PROFESSIONAL
    audience: Audience = Audience.GENERAL_AUDIENCE
    length: ContentLength = ContentLength.MEDIUM
    summary_type: SummaryType = SummaryType.SHORT
    content_format: ContentFormat = ContentFormat.BULLET_POINTS
    instructions: InstructionText | None = Field(
        default=None, description="Required by the content 'rewrite' task."
    )

    # Developer
    language: LanguageName = "python"
    framework: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    documentation_type: DocumentationType = DocumentationType.FUNCTION
    review_focus: list[ReviewFocus] = Field(default_factory=list)
    goals: list[ListItemText] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    requirements: list[ListItemText] = Field(
        default_factory=list, max_length=MAX_LIST_ITEMS
    )
    error_message: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=5_000)
    ] | None = None
    context: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=10_000)
    ] | None = None


# --- Requests ---------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """POST /api/conversations"""

    title: TitleText
    agent_type: AgentType

    model_config = {
        "json_schema_extra": {
            "example": {"title": "Python Code Review", "agent_type": "developer"}
        }
    }


class RenameConversationRequest(BaseModel):
    """PATCH /api/conversations/{id}

    Title is the only mutable field. agent_type, user_id, created_at and
    updated_at are all server-owned; there is deliberately no way to submit
    them.
    """

    title: TitleText


class MessageSource(BaseModel):
    """Where a message's source text came from, when it was not typed.

    Only the reference is kept — never a copy of the document text, which
    would duplicate up to 100,000 characters into every message. `filename`
    is denormalised on purpose so a transcript stays readable after the
    document is deleted.
    """

    type: str = "document"
    document_id: str
    filename: str


class SendMessageRequest(BaseModel):
    """POST /api/conversations/{id}/messages

    Either `prompt` or `document_id` must be supplied.

    When `document_id` is given, the source text is read from the stored
    document — the server's copy, never one sent by the client. A `prompt`
    alongside it is treated as the human label for the transcript, not as
    content, so it cannot be used to smuggle in substitute text.
    """

    task_type: TaskType
    prompt: PromptText | None = None
    document_id: str | None = Field(
        default=None,
        description="Use a stored document as the source text for this task.",
    )
    options: MessageOptions = Field(default_factory=MessageOptions)

    @model_validator(mode="after")
    def require_a_source(self) -> "SendMessageRequest":
        """A task needs something to work on."""
        if not self.prompt and not self.document_id:
            raise ValueError("Provide either prompt or document_id")
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "task_type": "summarize",
                "prompt": "Long article text to condense…",
            }
        }
    }


# --- Responses --------------------------------------------------------------


class ConversationData(BaseModel):
    """A conversation, as the API presents it.

    `user_id` is absent on purpose. The caller already knows who they are,
    and echoing an internal owner id back invites clients to start treating
    it as a parameter.
    """

    id: str
    title: str
    agent_type: AgentType
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageData(BaseModel):
    """One turn in a conversation."""

    id: str
    role: MessageRole
    content: str
    task_type: TaskType | None = None
    model: str | None = None
    created_at: datetime
    # Structured agent output — review findings, extracted entities and so on.
    # `content` is always the readable transcript text; this carries the shape
    # the agent pages already know how to render.
    data: dict | None = None
    # Present when the source text came from an uploaded document. Absent on
    # every message written before Phase 14, which is why it is nullable.
    source: MessageSource | None = None


class ConversationDetailData(ConversationData):
    """GET /api/conversations/{id} — metadata plus the full transcript."""

    messages: list[MessageData] = Field(default_factory=list)


class ConversationListData(BaseModel):
    """GET /api/conversations — one page of the caller's conversations."""

    conversations: list[ConversationData]
    page: int
    page_size: int
    total: int
    has_more: bool


class SendMessageData(BaseModel):
    """Both turns produced by one message request."""

    conversation_id: str
    user_message: MessageData
    assistant_message: MessageData
