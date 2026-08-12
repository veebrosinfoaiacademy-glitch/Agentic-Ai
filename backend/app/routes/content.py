"""Content Creation Agent endpoints.

Every handler does the same three things: take a validated request, call one
agent method, wrap the result in the standard envelope. No prompt building,
no Groq SDK, no database, no try/except — agent errors are already AppErrors
and the Phase 2 handlers turn them into the standard error envelope.
"""

from fastapi import APIRouter

from app.agents.content_agent import AgentResult, content_agent
from app.dependencies.quota import QuotaCheckedUser
from app.schemas.common_schemas import SuccessResponse, success
from app.schemas.content_schemas import (
    AudienceRequest,
    ExtractRequest,
    FormatRequest,
    GenerateRequest,
    RewriteRequest,
    SummarizeRequest,
    ToneRequest,
)

router = APIRouter(tags=["Content Agent"])


def _content_payload(result: AgentResult) -> dict:
    """Shape an agent result into the `data` field for text endpoints."""
    return {
        "content": result.content,
        "task_type": result.task_type,
        "model": result.model,
        "usage": result.usage,
    }


@router.post(
    "/generate",
    response_model=SuccessResponse,
    summary="Generate new content from a topic",
    description=(
        "Writes original content matching the requested type, tone, audience "
        "and length."
    ),
)
def generate_content(request: GenerateRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.generate(
        topic=request.topic,
        content_type=request.content_type,
        tone=request.tone,
        audience=request.audience,
        length=request.length,
        additional_instructions=request.additional_instructions,
    )
    return success(data=_content_payload(result), message="Content generated successfully")


@router.post(
    "/summarize",
    response_model=SuccessResponse,
    summary="Summarize supplied text",
    description=(
        "Condenses the source text into a short summary, a detailed summary "
        "or bullet points. Uses only information present in the source."
    ),
)
def summarize_content(request: SummarizeRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.summarize(text=request.text, summary_type=request.summary_type)
    return success(data=_content_payload(result), message="Content summarized successfully")


@router.post(
    "/rewrite",
    response_model=SuccessResponse,
    summary="Rewrite text following instructions",
    description="Improves the source text while preserving its meaning.",
)
def rewrite_content(request: RewriteRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.rewrite(text=request.text, instructions=request.instructions)
    return success(data=_content_payload(result), message="Content rewritten successfully")


@router.post(
    "/tone",
    response_model=SuccessResponse,
    summary="Change the tone of text",
    description="Rewrites the source in a different tone. Facts are unchanged.",
)
def transform_tone(request: ToneRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.transform_tone(text=request.text, tone=request.tone)
    return success(data=_content_payload(result), message="Tone transformed successfully")


@router.post(
    "/audience",
    response_model=SuccessResponse,
    summary="Adapt text for a different audience",
    description=(
        "Adjusts vocabulary, depth and examples for the target reader while "
        "preserving the underlying facts."
    ),
)
def adapt_audience(request: AudienceRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.adapt_audience(text=request.text, audience=request.audience)
    return success(data=_content_payload(result), message="Content adapted successfully")


@router.post(
    "/format",
    response_model=SuccessResponse,
    summary="Reformat text into a different structure",
    description="Restructures the source into the requested format.",
)
def transform_format(request: FormatRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.transform_format(text=request.text, content_format=request.format)
    return success(data=_content_payload(result), message="Content reformatted successfully")


@router.post(
    "/extract",
    response_model=SuccessResponse,
    summary="Extract structured information from text",
    description=(
        "Returns entities, key points, facts and keywords found in the source. "
        "Model output is parsed and validated before it is returned."
    ),
)
def extract_information(request: ExtractRequest, user: QuotaCheckedUser) -> dict:
    result = content_agent.extract_information(text=request.text)

    # structured is always populated here — extract_information either sets
    # it or raises. The `or {}` keeps type checkers happy.
    payload = dict(result.structured or {})
    payload.update(
        {"task_type": result.task_type, "model": result.model, "usage": result.usage}
    )
    return success(data=payload, message="Information extracted successfully")
