"""The Content Creation Agent.

This is what makes the project an "agent" system rather than a chat wrapper.
For each task the agent decides three things:

1. which system prompt establishes the right role and rules,
2. how to phrase the user message from the request fields,
3. what sampling settings suit the task.

It then calls the shared Groq service and validates what comes back. It never
imports the Groq SDK, never touches MongoDB, and never knows about HTTP.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError, field_validator

from app.prompts.content_prompts import (
    AUDIENCE_ADAPTATION_PROMPT,
    CONTENT_GENERATION_PROMPT,
    FORMAT_TRANSFORMATION_PROMPT,
    INFORMATION_EXTRACTION_PROMPT,
    REWRITE_PROMPT,
    SUMMARIZATION_PROMPT,
    TONE_TRANSFORMATION_PROMPT,
    build_audience_prompt,
    build_extraction_prompt,
    build_format_prompt,
    build_generation_prompt,
    build_rewrite_prompt,
    build_summarization_prompt,
    build_tone_prompt,
)
from app.schemas.content_schemas import (
    Audience,
    ContentFormat,
    ContentLength,
    ContentType,
    SummaryType,
    Tone,
)
from app.services.groq_service import groq_service
from app.utils.errors import AppError

logger = logging.getLogger("app.agents.content")


# --- Sampling strategy ------------------------------------------------------
#
# Temperature controls how much randomness the model uses when picking each
# next word. The right value depends entirely on the task, which is why these
# live in code next to the tasks rather than in .env as one global setting.
#
#   generation   0.75  new writing, so variety is a feature — two runs of the
#                      same topic should not read identically
#   rewrite      0.50  needs some freedom to rephrase, but must stay anchored
#   tone         0.40  style may vary; facts must not
#   audience     0.40  same reasoning as tone
#   format       0.30  mostly mechanical restructuring
#   summarize    0.25  should be faithful and reproducible, not creative
#   extraction   0.00  near-deterministic; invented entities are the main
#                      failure mode and randomness is what causes them
TEMPERATURE_GENERATION = 0.75
TEMPERATURE_REWRITE = 0.5
TEMPERATURE_TONE = 0.4
TEMPERATURE_AUDIENCE = 0.4
TEMPERATURE_FORMAT = 0.3
TEMPERATURE_SUMMARIZE = 0.25
TEMPERATURE_EXTRACTION = 0.0

MAX_TOKENS_LONG_FORM = 3000
MAX_TOKENS_STANDARD = 2000
MAX_TOKENS_EXTRACTION = 1500


@dataclass
class AgentResult:
    """What the agent hands back to a route.

    Internal to the agent layer on purpose — routes choose what part of this
    to expose, and the agent stays usable from non-HTTP callers later.
    """

    content: str
    task_type: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    structured: dict[str, list[str]] | None = None


class _ExtractionPayload(BaseModel):
    """Validates the JSON the model returns for extraction.

    Everything defaults to an empty list, and the validator coerces loosely
    shaped items instead of rejecting the whole response. Models sometimes
    return `[{"name": "Acme", "type": "org"}]` where we asked for strings;
    that is worth salvaging, not worth a 502.
    """

    entities: list[str] = []
    key_points: list[str] = []
    facts: list[str] = []
    keywords: list[str] = []

    @field_validator("entities", "key_points", "facts", "keywords", mode="before")
    @classmethod
    def coerce_items(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            return []

        items: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = " - ".join(str(v) for v in item.values() if v)
            else:
                text = str(item)
            if text.strip():
                items.append(text.strip())
        return items


class ContentAgent:
    """Performs the seven content tasks."""

    def __init__(self) -> None:
        self._ai = groq_service

    # --- Shared plumbing ----------------------------------------------------

    def _run(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = MAX_TOKENS_STANDARD,
        json_mode: bool = False,
    ) -> AgentResult:
        """Send one task to the AI service and wrap the result.

        Every public method funnels through here, so logging and result
        shaping are defined once.
        """
        logger.info("Content task '%s' starting (temperature=%s)", task_type, temperature)

        result = self._ai.generate(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

        logger.info("Content task '%s' completed (%d chars)", task_type, len(result.content))

        return AgentResult(
            content=result.content,
            task_type=task_type,
            model=result.model,
            usage=result.usage,
        )

    # --- Tasks --------------------------------------------------------------

    def generate(
        self,
        topic: str,
        content_type: ContentType,
        tone: Tone,
        audience: Audience,
        length: ContentLength,
        additional_instructions: str | None = None,
    ) -> AgentResult:
        """Write new content from a topic and a set of constraints."""
        return self._run(
            task_type="generation",
            system_prompt=CONTENT_GENERATION_PROMPT,
            user_prompt=build_generation_prompt(
                topic=topic,
                content_type=content_type,
                tone=tone,
                audience=audience,
                length=length,
                additional_instructions=additional_instructions,
            ),
            temperature=TEMPERATURE_GENERATION,
            max_tokens=MAX_TOKENS_LONG_FORM,
        )

    def summarize(self, text: str, summary_type: SummaryType) -> AgentResult:
        """Condense supplied text. Grounded — no new facts."""
        return self._run(
            task_type="summarization",
            system_prompt=SUMMARIZATION_PROMPT,
            user_prompt=build_summarization_prompt(text, summary_type),
            temperature=TEMPERATURE_SUMMARIZE,
        )

    def rewrite(self, text: str, instructions: str) -> AgentResult:
        """Improve supplied text according to the user's instructions."""
        return self._run(
            task_type="rewrite",
            system_prompt=REWRITE_PROMPT,
            user_prompt=build_rewrite_prompt(text, instructions),
            temperature=TEMPERATURE_REWRITE,
        )

    def transform_tone(self, text: str, tone: Tone) -> AgentResult:
        """Change style while holding the facts fixed."""
        return self._run(
            task_type="tone_transformation",
            system_prompt=TONE_TRANSFORMATION_PROMPT,
            user_prompt=build_tone_prompt(text, tone),
            temperature=TEMPERATURE_TONE,
        )

    def adapt_audience(self, text: str, audience: Audience) -> AgentResult:
        """Re-pitch the explanation depth for a different reader."""
        return self._run(
            task_type="audience_adaptation",
            system_prompt=AUDIENCE_ADAPTATION_PROMPT,
            user_prompt=build_audience_prompt(text, audience),
            temperature=TEMPERATURE_AUDIENCE,
        )

    def transform_format(self, text: str, content_format: ContentFormat) -> AgentResult:
        """Restructure into a different presentation format."""
        return self._run(
            task_type="format_transformation",
            system_prompt=FORMAT_TRANSFORMATION_PROMPT,
            user_prompt=build_format_prompt(text, content_format),
            temperature=TEMPERATURE_FORMAT,
        )

    def extract_information(self, text: str) -> AgentResult:
        """Pull structured information out of supplied text.

        Two layers of defence against bad model output: JSON mode asks the
        provider to constrain the response, and `_parse_extraction` still
        validates whatever arrives. Model-generated JSON is never trusted on
        sight.
        """
        result = self._run(
            task_type="extraction",
            system_prompt=INFORMATION_EXTRACTION_PROMPT,
            user_prompt=build_extraction_prompt(text),
            temperature=TEMPERATURE_EXTRACTION,
            max_tokens=MAX_TOKENS_EXTRACTION,
            json_mode=True,
        )
        result.structured = self._parse_extraction(result.content)
        return result

    # --- Output parsing -----------------------------------------------------

    @staticmethod
    def _strip_code_fences(raw: str) -> str:
        """Remove ```json ... ``` wrappers some models add despite instructions."""
        fenced = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", raw, re.DOTALL)
        return fenced.group(1) if fenced else raw.strip()

    def _parse_extraction(self, raw: str) -> dict[str, list[str]]:
        """Turn the model's reply into a validated dict.

        Raises AppError rather than returning half-parsed data — a caller
        that receives `{}` cannot tell "nothing found" from "parsing broke".
        """
        candidate = self._strip_code_fences(raw)

        # Some models still prepend a sentence. Fall back to the outermost
        # braces before giving up.
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start == -1 or end <= start:
                logger.error("Extraction returned no JSON object")
                raise AppError(
                    code="AI_INVALID_OUTPUT",
                    message="AI returned an unexpected format. Please try again.",
                    status_code=502,
                ) from None
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                logger.error("Extraction returned malformed JSON")
                raise AppError(
                    code="AI_INVALID_OUTPUT",
                    message="AI returned an unexpected format. Please try again.",
                    status_code=502,
                ) from None

        if not isinstance(parsed, dict):
            logger.error("Extraction returned %s, expected an object", type(parsed).__name__)
            raise AppError(
                code="AI_INVALID_OUTPUT",
                message="AI returned an unexpected format. Please try again.",
                status_code=502,
            )

        try:
            payload = _ExtractionPayload.model_validate(parsed)
        except ValidationError:
            logger.error("Extraction JSON failed schema validation")
            raise AppError(
                code="AI_INVALID_OUTPUT",
                message="AI returned an unexpected format. Please try again.",
                status_code=502,
            ) from None

        return payload.model_dump()


# Single shared instance, matching the mongodb / groq_service pattern.
content_agent = ContentAgent()
