"""Request and response models for the Content Creation Agent.

Enums rather than free strings: the application only supports a fixed set of
tones, audiences and formats, so anything else is a client bug. Rejecting it
at the edge with a 422 is cheaper and clearer than sending nonsense to Groq
and paying for a confused answer.

FastAPI also renders these enums as dropdowns in Swagger, which doubles as
documentation of what the agent can actually do.
"""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# --- Input limits -----------------------------------------------------------
#
# Source text is capped at 20,000 characters (~5,000 tokens). That leaves
# plenty of room inside the model's context window for the system prompt and
# the reply, and is generous enough for a long article or a pasted document.
# Topics and instructions are short by nature, so they get tight caps — an
# 8,000-character "topic" is a misuse of the field, not a long topic.
MAX_TEXT_CHARS = 20_000
MAX_TOPIC_CHARS = 300
MAX_INSTRUCTIONS_CHARS = 1_000

# strip_whitespace runs before min_length, so "   " collapses to "" and is
# rejected rather than reaching the model as a blank request.
SourceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_CHARS),
]
TopicText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TOPIC_CHARS),
]
InstructionsText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_INSTRUCTIONS_CHARS
    ),
]


# --- Controlled vocabularies ------------------------------------------------


class ContentType(str, Enum):
    BLOG = "blog"
    ARTICLE = "article"
    EMAIL = "email"
    SOCIAL_MEDIA = "social_media"
    TECHNICAL_EXPLANATION = "technical_explanation"
    PRODUCT_DESCRIPTION = "product_description"


class Tone(str, Enum):
    PROFESSIONAL = "professional"
    FORMAL = "formal"
    FRIENDLY = "friendly"
    CASUAL = "casual"
    PERSUASIVE = "persuasive"
    SIMPLE = "simple"
    ACADEMIC = "academic"


class Audience(str, Enum):
    BEGINNER = "beginner"
    STUDENT = "student"
    DEVELOPER = "developer"
    TECHNICAL_PROFESSIONAL = "technical_professional"
    GENERAL_AUDIENCE = "general_audience"
    EXECUTIVE = "executive"


class ContentLength(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class SummaryType(str, Enum):
    SHORT = "short"
    DETAILED = "detailed"
    BULLET_POINTS = "bullet_points"


class ContentFormat(str, Enum):
    PARAGRAPH = "paragraph"
    BULLET_POINTS = "bullet_points"
    ARTICLE = "article"
    EMAIL = "email"
    REPORT = "report"
    SOCIAL_MEDIA = "social_media"


# --- Requests ---------------------------------------------------------------


class GenerateRequest(BaseModel):
    """POST /api/content/generate"""

    topic: TopicText = Field(description="What the content should be about.")
    content_type: ContentType = ContentType.BLOG
    tone: Tone = Tone.PROFESSIONAL
    audience: Audience = Audience.GENERAL_AUDIENCE
    length: ContentLength = ContentLength.MEDIUM
    additional_instructions: InstructionsText | None = Field(
        default=None, description="Optional extra guidance for the writer."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "topic": "Artificial Intelligence in Education",
                "content_type": "blog",
                "tone": "professional",
                "audience": "student",
                "length": "medium",
                "additional_instructions": "Use simple examples.",
            }
        }
    }


class SummarizeRequest(BaseModel):
    """POST /api/content/summarize"""

    text: SourceText = Field(description="The source text to summarise.")
    summary_type: SummaryType = SummaryType.SHORT


class RewriteRequest(BaseModel):
    """POST /api/content/rewrite"""

    text: SourceText
    instructions: InstructionsText = Field(
        description="How the text should be improved."
    )


class ToneRequest(BaseModel):
    """POST /api/content/tone"""

    text: SourceText
    tone: Tone


class AudienceRequest(BaseModel):
    """POST /api/content/audience"""

    text: SourceText
    audience: Audience


class FormatRequest(BaseModel):
    """POST /api/content/format"""

    text: SourceText
    format: ContentFormat


class ExtractRequest(BaseModel):
    """POST /api/content/extract"""

    text: SourceText


# --- Responses --------------------------------------------------------------


class ContentData(BaseModel):
    """`data` payload for the text-producing endpoints."""

    content: str
    task_type: str
    model: str
    usage: dict[str, int] = {}


class ExtractionData(BaseModel):
    """`data` payload for /extract.

    Every field defaults to an empty list so a model that omits a key
    produces an empty section rather than a failed request.
    """

    entities: list[str] = []
    key_points: list[str] = []
    facts: list[str] = []
    keywords: list[str] = []
    task_type: str = "extraction"
    model: str = ""
    usage: dict[str, int] = {}
