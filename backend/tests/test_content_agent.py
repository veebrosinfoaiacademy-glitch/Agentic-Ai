"""Phase 5 tests: Content Agent behaviour, entirely offline.

These verify the three decisions the agent makes for each task — which system
prompt, what user message, which sampling settings — plus how it handles the
model's output. The AI call itself is replaced by a recorder.
"""

import json

import pytest

from app.agents.content_agent import (
    TEMPERATURE_EXTRACTION,
    TEMPERATURE_GENERATION,
    TEMPERATURE_SUMMARIZE,
    ContentAgent,
    content_agent,
)
from app.prompts import content_prompts
from app.schemas.content_schemas import (
    Audience,
    ContentFormat,
    ContentLength,
    ContentType,
    SummaryType,
    Tone,
)
from app.utils.errors import AppError
from tests.conftest import GenerateRecorder

SOURCE = "Acme Corp released Widget 3 in March 2024. It cut processing time by 40%."


# --- Each task selects its own system prompt --------------------------------


def test_each_task_uses_its_own_system_prompt(
    recorded_generate: GenerateRecorder,
) -> None:
    """A regression here would mean one task silently borrowing another's rules."""
    cases = [
        (lambda: content_agent.summarize(SOURCE, SummaryType.SHORT),
         content_prompts.SUMMARIZATION_PROMPT),
        (lambda: content_agent.rewrite(SOURCE, "Make it clearer."),
         content_prompts.REWRITE_PROMPT),
        (lambda: content_agent.transform_tone(SOURCE, Tone.CASUAL),
         content_prompts.TONE_TRANSFORMATION_PROMPT),
        (lambda: content_agent.adapt_audience(SOURCE, Audience.BEGINNER),
         content_prompts.AUDIENCE_ADAPTATION_PROMPT),
        (lambda: content_agent.transform_format(SOURCE, ContentFormat.REPORT),
         content_prompts.FORMAT_TRANSFORMATION_PROMPT),
    ]

    for run_task, expected_prompt in cases:
        run_task()
        assert recorded_generate.system_prompt == expected_prompt


def test_generation_uses_the_generation_prompt(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.generate(
        topic="AI in Education",
        content_type=ContentType.BLOG,
        tone=Tone.PROFESSIONAL,
        audience=Audience.STUDENT,
        length=ContentLength.MEDIUM,
    )

    assert recorded_generate.system_prompt == content_prompts.CONTENT_GENERATION_PROMPT


def test_extraction_uses_the_extraction_prompt_and_json_mode(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = json.dumps({"entities": [], "key_points": []})

    content_agent.extract_information(SOURCE)

    assert recorded_generate.system_prompt == content_prompts.INFORMATION_EXTRACTION_PROMPT
    assert recorded_generate.last["json_mode"] is True


def test_prose_tasks_do_not_request_json_mode(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.summarize(SOURCE, SummaryType.SHORT)

    assert recorded_generate.last["json_mode"] is False


# --- Prompt regression: required context reaches the model ------------------


def test_generation_prompt_carries_every_requested_constraint(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.generate(
        topic="Quantum Computing",
        content_type=ContentType.EMAIL,
        tone=Tone.PERSUASIVE,
        audience=Audience.EXECUTIVE,
        length=ContentLength.SHORT,
        additional_instructions="Mention cost savings.",
    )

    prompt = recorded_generate.user_prompt
    assert "Quantum Computing" in prompt
    assert content_prompts.CONTENT_TYPE_GUIDANCE[ContentType.EMAIL] in prompt
    assert content_prompts.TONE_GUIDANCE[Tone.PERSUASIVE] in prompt
    assert content_prompts.AUDIENCE_GUIDANCE[Audience.EXECUTIVE] in prompt
    assert content_prompts.LENGTH_GUIDANCE[ContentLength.SHORT] in prompt
    assert "Mention cost savings." in prompt


def test_generation_prompt_omits_absent_optional_instructions(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.generate(
        topic="Topic",
        content_type=ContentType.BLOG,
        tone=Tone.SIMPLE,
        audience=Audience.BEGINNER,
        length=ContentLength.SHORT,
        additional_instructions=None,
    )

    assert "Additional instructions" not in recorded_generate.user_prompt


def test_summarization_prompt_carries_source_and_style(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.summarize(SOURCE, SummaryType.BULLET_POINTS)

    prompt = recorded_generate.user_prompt
    assert SOURCE in prompt
    assert "Summary type: bullet_points" in prompt
    assert content_prompts.SUMMARY_TYPE_GUIDANCE[SummaryType.BULLET_POINTS] in prompt
    assert "Follow the requested summary type exactly" in prompt


def test_rewrite_prompt_carries_source_and_instructions(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.rewrite(SOURCE, "Make it more concise.")

    prompt = recorded_generate.user_prompt
    assert SOURCE in prompt
    assert "Make it more concise." in prompt


def test_tone_prompt_carries_source_and_requested_tone(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.transform_tone(SOURCE, Tone.ACADEMIC)

    prompt = recorded_generate.user_prompt
    assert SOURCE in prompt
    assert "academic" in prompt
    assert content_prompts.TONE_GUIDANCE[Tone.ACADEMIC] in prompt


def test_audience_prompt_carries_source_and_audience(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.adapt_audience(SOURCE, Audience.DEVELOPER)

    prompt = recorded_generate.user_prompt
    assert SOURCE in prompt
    assert content_prompts.AUDIENCE_GUIDANCE[Audience.DEVELOPER] in prompt


def test_format_prompt_carries_source_and_format(
    recorded_generate: GenerateRecorder,
) -> None:
    content_agent.transform_format(SOURCE, ContentFormat.BULLET_POINTS)

    prompt = recorded_generate.user_prompt
    assert SOURCE in prompt
    assert content_prompts.FORMAT_GUIDANCE[ContentFormat.BULLET_POINTS] in prompt


def test_extraction_prompt_carries_the_source(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    content_agent.extract_information(SOURCE)

    assert SOURCE in recorded_generate.user_prompt


# --- Grounding rules are present in the prompts -----------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        content_prompts.SUMMARIZATION_PROMPT,
        content_prompts.REWRITE_PROMPT,
        content_prompts.TONE_TRANSFORMATION_PROMPT,
        content_prompts.AUDIENCE_ADAPTATION_PROMPT,
        content_prompts.FORMAT_TRANSFORMATION_PROMPT,
    ],
)
def test_transformation_prompts_forbid_inventing_facts(prompt: str) -> None:
    """Every task that transforms user text must be grounded in that text."""
    assert "Do not add facts" in prompt


def test_extraction_prompt_forbids_inventing_entities() -> None:
    assert "never infer, guess or invent" in (
        content_prompts.INFORMATION_EXTRACTION_PROMPT.lower()
    )


def test_tone_prompt_requires_meaning_to_stay_fixed() -> None:
    assert "factual meaning must stay identical" in (
        content_prompts.TONE_TRANSFORMATION_PROMPT.lower()
    )


def test_every_system_prompt_declares_role_task_and_constraints() -> None:
    prompts = [
        content_prompts.CONTENT_GENERATION_PROMPT,
        content_prompts.SUMMARIZATION_PROMPT,
        content_prompts.REWRITE_PROMPT,
        content_prompts.TONE_TRANSFORMATION_PROMPT,
        content_prompts.AUDIENCE_ADAPTATION_PROMPT,
        content_prompts.FORMAT_TRANSFORMATION_PROMPT,
        content_prompts.INFORMATION_EXTRACTION_PROMPT,
    ]
    for prompt in prompts:
        assert prompt.lower().startswith("you are")  # role
        assert "TASK" in prompt
        assert "CONSTRAINTS" in prompt
        assert "OUTPUT" in prompt


# --- Sampling strategy ------------------------------------------------------


def test_creative_and_factual_tasks_use_different_temperatures(
    recorded_generate: GenerateRecorder,
) -> None:
    """Generation should be varied; extraction should be near-deterministic."""
    content_agent.generate(
        topic="T",
        content_type=ContentType.BLOG,
        tone=Tone.CASUAL,
        audience=Audience.BEGINNER,
        length=ContentLength.SHORT,
    )
    assert recorded_generate.last["temperature"] == TEMPERATURE_GENERATION

    content_agent.summarize(SOURCE, SummaryType.SHORT)
    assert recorded_generate.last["temperature"] == TEMPERATURE_SUMMARIZE

    recorded_generate.content = "{}"
    content_agent.extract_information(SOURCE)
    assert recorded_generate.last["temperature"] == TEMPERATURE_EXTRACTION

    assert TEMPERATURE_EXTRACTION < TEMPERATURE_SUMMARIZE < TEMPERATURE_GENERATION


# --- Result shape -----------------------------------------------------------


def test_result_reports_task_type_model_and_usage(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "A summary."

    result = content_agent.summarize(SOURCE, SummaryType.SHORT)

    assert result.content == "A summary."
    assert result.task_type == "summarization"
    assert result.model
    assert result.usage["total_tokens"] == 100


@pytest.mark.parametrize(
    ("run_task", "expected_task_type"),
    [
        (lambda: content_agent.rewrite(SOURCE, "clearer"), "rewrite"),
        (lambda: content_agent.transform_tone(SOURCE, Tone.FORMAL), "tone_transformation"),
        (
            lambda: content_agent.adapt_audience(SOURCE, Audience.STUDENT),
            "audience_adaptation",
        ),
        (
            lambda: content_agent.transform_format(SOURCE, ContentFormat.EMAIL),
            "format_transformation",
        ),
    ],
)
def test_task_types_are_labelled_correctly(
    recorded_generate: GenerateRecorder, run_task, expected_task_type: str
) -> None:
    assert run_task().task_type == expected_task_type


# --- Extraction parsing: model output is never trusted ----------------------


def test_extraction_parses_clean_json(recorded_generate: GenerateRecorder) -> None:
    recorded_generate.content = json.dumps(
        {
            "entities": ["Acme Corp", "Widget 3"],
            "key_points": ["Widget 3 was released."],
            "facts": ["Processing time fell by 40%."],
            "keywords": ["widget", "performance"],
        }
    )

    result = content_agent.extract_information(SOURCE)

    assert result.structured is not None
    assert result.structured["entities"] == ["Acme Corp", "Widget 3"]
    assert result.structured["facts"] == ["Processing time fell by 40%."]


def test_extraction_strips_markdown_code_fences(
    recorded_generate: GenerateRecorder,
) -> None:
    """Models add ```json fences despite being told not to."""
    recorded_generate.content = '```json\n{"entities": ["Acme Corp"]}\n```'

    result = content_agent.extract_information(SOURCE)

    assert result.structured is not None
    assert result.structured["entities"] == ["Acme Corp"]


def test_extraction_recovers_json_after_a_preamble(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = 'Here is the JSON:\n{"keywords": ["widget"]}'

    result = content_agent.extract_information(SOURCE)

    assert result.structured is not None
    assert result.structured["keywords"] == ["widget"]


def test_extraction_fills_missing_keys_with_empty_lists(
    recorded_generate: GenerateRecorder,
) -> None:
    """A missing category is an empty section, not a failed request."""
    recorded_generate.content = json.dumps({"entities": ["Acme Corp"]})

    result = content_agent.extract_information(SOURCE)

    assert result.structured == {
        "entities": ["Acme Corp"],
        "key_points": [],
        "facts": [],
        "keywords": [],
    }


def test_extraction_coerces_object_items_into_strings(
    recorded_generate: GenerateRecorder,
) -> None:
    """Models often return objects where we asked for strings. Salvage them."""
    recorded_generate.content = json.dumps(
        {"entities": [{"name": "Acme Corp", "type": "organisation"}]}
    )

    result = content_agent.extract_information(SOURCE)

    assert result.structured is not None
    assert result.structured["entities"] == ["Acme Corp - organisation"]


@pytest.mark.parametrize(
    "bad_output",
    [
        "This text contains no JSON at all.",
        '{"entities": [unquoted]}',
        "[1, 2, 3]",
        "",
    ],
    ids=["no-json", "malformed", "array-not-object", "empty"],
)
def test_malformed_extraction_output_raises_a_clean_error(
    recorded_generate: GenerateRecorder, bad_output: str
) -> None:
    """Bad JSON must fail loudly, not return a half-parsed dict."""
    recorded_generate.content = bad_output or "not json"

    with pytest.raises(AppError) as exc_info:
        content_agent.extract_information(SOURCE)

    assert exc_info.value.code == "AI_INVALID_OUTPUT"
    assert exc_info.value.status_code == 502


# --- Provider failures propagate unchanged ----------------------------------


def test_provider_errors_are_not_swallowed(failing_generate: GenerateRecorder) -> None:
    """The agent adds no error handling of its own — Phase 4 already did it."""
    with pytest.raises(AppError) as exc_info:
        content_agent.summarize(SOURCE, SummaryType.SHORT)

    assert exc_info.value.code == "AI_PROVIDER_ERROR"


# --- The agent uses the shared service --------------------------------------


def test_agent_uses_the_shared_groq_service() -> None:
    """No second AI client anywhere in the agent."""
    from app.services.groq_service import groq_service as shared

    assert ContentAgent()._ai is shared
