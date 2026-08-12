"""Request/response models for the AI verification endpoint.

Phase 5 and 6 add richer schemas (content type, tone, audience, language).
These stay minimal on purpose — this endpoint exists only to prove the
FastAPI -> Groq Service -> Groq API path works.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# 10,000 characters is roughly 2,500 tokens — comfortably inside the model's
# context window while leaving room for the reply, and large enough for a
# pasted article or source file. Unbounded input would let one request burn
# the whole free-tier rate limit.
MAX_PROMPT_CHARS = 10_000

# strip_whitespace runs before min_length, so a prompt of "   " becomes ""
# and is rejected rather than sent to Groq as a blank request.
PromptText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT_CHARS),
]


class AITestRequest(BaseModel):
    """Body of POST /api/ai/test."""

    prompt: PromptText = Field(
        description="The text to send to the model.",
        examples=["Explain what an AI agent is in one sentence."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {"prompt": "Explain what an AI agent is in one sentence."}
        }
    }


class AITestData(BaseModel):
    """Payload returned inside the success envelope's `data` field.

    Note what is absent: no API key, no request headers, no raw SDK object.
    The model ID and token usage are safe and useful for a demo.
    """

    content: str
    model: str
    usage: dict[str, int] = {}
