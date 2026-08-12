"""Defensive parsing of model-generated output.

Shared by both agents. LLM output is untrusted input: even with the
provider's JSON mode enabled, models add prose preambles, wrap responses in
markdown fences, omit keys, or return an array where an object was asked for.
Every one of those is handled here so no agent has to reinvent it.

The rule throughout: fail loudly with AI_INVALID_OUTPUT rather than return a
half-parsed object. A caller that receives `{}` cannot tell "nothing found"
from "parsing broke".
"""

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.utils.errors import AppError

logger = logging.getLogger("app.ai_output")

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCED_BLOCK = re.compile(r"^\s*```[a-zA-Z0-9+#._-]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _invalid_output(context: str, reason: str) -> AppError:
    """Build the standard error for unusable model output.

    The reason is logged for us; the client gets a generic, actionable
    message because the model's malformed text is not their problem.
    """
    logger.error("Invalid AI output for '%s': %s", context, reason)
    return AppError(
        code="AI_INVALID_OUTPUT",
        message="AI returned an unexpected format. Please try again.",
        status_code=502,
    )


def strip_code_fences(text: str) -> str:
    """Remove a surrounding ```lang ... ``` wrapper if present.

    Models add fences even when told not to. Stripping them here means the
    API returns clean code and the frontend never has to parse markdown.
    Text that is not fenced is returned unchanged apart from trimming.
    """
    if not text:
        return ""
    match = _FENCED_BLOCK.match(text)
    return (match.group(1) if match else text).strip()


def parse_json_object(raw: str, context: str) -> dict:
    """Parse model output into a JSON object.

    Tries three things in order, each a real failure mode seen from LLMs:
      1. the whole response as JSON,
      2. the response with markdown fences stripped,
      3. the substring between the outermost braces, for replies that open
         with something like "Here is the JSON:".
    """
    candidates = [raw, strip_code_fences(raw)]

    unfenced = candidates[1]
    start, end = unfenced.find("{"), unfenced.rfind("}")
    if start != -1 and end > start:
        candidates.append(unfenced[start : end + 1])

    for candidate in candidates:
        if not candidate or not candidate.strip():
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise _invalid_output(context, f"expected an object, got {type(parsed).__name__}")

    raise _invalid_output(context, "response contained no valid JSON object")


def validate_payload(model: type[ModelT], data: dict, context: str) -> ModelT:
    """Validate a parsed dict against a Pydantic model.

    Payload models give every field a default, so a missing key becomes an
    empty section rather than a failed request. Validation failing here means
    the shape was genuinely wrong, not merely incomplete.
    """
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise _invalid_output(context, f"schema validation failed: {exc.error_count()} errors")


def parse_structured(model: type[ModelT], raw: str, context: str) -> ModelT:
    """Parse and validate model output in one step."""
    return validate_payload(model, parse_json_object(raw, context), context)


def coerce_string_list(value: object) -> list[str]:
    """Normalise a field that should be a list of strings.

    Models frequently return a bare string, or a list of objects, where a
    list of strings was requested. Salvaging those is better than failing an
    otherwise-good response.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
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
