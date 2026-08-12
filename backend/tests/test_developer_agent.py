"""Phase 6 tests: Developer Agent behaviour, entirely offline.

Covers prompt selection, prompt content, sampling settings, structured-output
parsing, and the anti-fabrication guards. No real Groq calls.
"""

import json

import pytest

from app.agents.developer_agent import (
    TEMPERATURE_DEBUG,
    TEMPERATURE_GENERATION,
    TEMPERATURE_REVIEW,
    DeveloperAgent,
    developer_agent,
)
from app.prompts import developer_prompts
from app.schemas.developer_schemas import DocumentationType, ReviewFocus
from app.utils.errors import AppError
from tests.conftest import GenerateRecorder

# Four lines, so any cited line number above 4 is fabricated.
CODE = "def add(a, b):\n    total = a + b\n    return total\n"
LANG = "python"


def _json(payload: dict) -> str:
    return json.dumps(payload)


# --- Prompt selection -------------------------------------------------------


def test_each_task_uses_its_own_system_prompt(
    recorded_generate: GenerateRecorder,
) -> None:
    cases = [
        (
            lambda: developer_agent.generate_code(LANG, "Add two numbers"),
            developer_prompts.CODE_GENERATION_PROMPT,
        ),
        (
            lambda: developer_agent.explain_code(LANG, CODE),
            developer_prompts.CODE_EXPLANATION_PROMPT,
        ),
        (
            lambda: developer_agent.review_code(LANG, CODE),
            developer_prompts.CODE_REVIEW_PROMPT,
        ),
        (
            lambda: developer_agent.refactor_code(LANG, CODE),
            developer_prompts.CODE_REFACTOR_PROMPT,
        ),
        (
            lambda: developer_agent.generate_tests(LANG, CODE),
            developer_prompts.TEST_GENERATION_PROMPT,
        ),
        (
            lambda: developer_agent.analyse_bug(LANG, CODE, "TypeError"),
            developer_prompts.BUG_ANALYSIS_PROMPT,
        ),
        (
            lambda: developer_agent.generate_documentation(
                LANG, CODE, DocumentationType.FUNCTION
            ),
            developer_prompts.DOCUMENTATION_PROMPT,
        ),
    ]

    for run_task, expected in cases:
        recorded_generate.content = "{}"
        run_task()
        assert recorded_generate.system_prompt == expected


def test_every_task_requests_json_mode(recorded_generate: GenerateRecorder) -> None:
    recorded_generate.content = "{}"

    developer_agent.review_code(LANG, CODE)
    assert recorded_generate.last["json_mode"] is True

    developer_agent.explain_code(LANG, CODE)
    assert recorded_generate.last["json_mode"] is True


def test_agent_uses_the_shared_groq_service() -> None:
    from app.services.groq_service import groq_service as shared

    assert DeveloperAgent()._ai is shared


# --- Prompt regression: grounding rules -------------------------------------

ALL_PROMPTS = [
    developer_prompts.CODE_GENERATION_PROMPT,
    developer_prompts.CODE_EXPLANATION_PROMPT,
    developer_prompts.CODE_REVIEW_PROMPT,
    developer_prompts.CODE_REFACTOR_PROMPT,
    developer_prompts.TEST_GENERATION_PROMPT,
    developer_prompts.BUG_ANALYSIS_PROMPT,
    developer_prompts.DOCUMENTATION_PROMPT,
]


@pytest.mark.parametrize("prompt", ALL_PROMPTS)
def test_every_prompt_forbids_claiming_execution(prompt: str) -> None:
    """This system never runs code, so no prompt may allow claiming it did."""
    lowered = prompt.lower()
    assert "does not execute code" in lowered
    assert "never claim you ran" in lowered


@pytest.mark.parametrize("prompt", ALL_PROMPTS)
def test_every_prompt_forbids_inventing_dependencies(prompt: str) -> None:
    assert "never invent functions, libraries, apis" in prompt.lower()


@pytest.mark.parametrize("prompt", ALL_PROMPTS)
def test_every_prompt_declares_role_task_and_output(prompt: str) -> None:
    assert prompt.lower().startswith("you are")
    assert "TASK" in prompt
    assert "CONSTRAINTS" in prompt
    assert "OUTPUT" in prompt


def test_review_prompt_forbids_inventing_line_numbers() -> None:
    lowered = developer_prompts.CODE_REVIEW_PROMPT.lower()
    assert "never invent line numbers" in lowered
    assert "use null" in lowered


def test_review_prompt_forbids_claiming_confirmed_vulnerabilities() -> None:
    lowered = developer_prompts.CODE_REVIEW_PROMPT.lower()
    assert "never claim a vulnerability is confirmed" in lowered


def test_review_prompt_defines_severity_by_impact() -> None:
    prompt = developer_prompts.CODE_REVIEW_PROMPT
    for severity in ("critical", "high", "medium", "low", "info"):
        assert severity in prompt
    assert "not personal style preference" in prompt.lower()


def test_refactor_prompt_requires_behaviour_preservation() -> None:
    lowered = developer_prompts.CODE_REFACTOR_PROMPT.lower()
    assert "preserve the existing intended behaviour" in lowered
    assert "never silently alter business logic" in lowered


def test_test_prompt_states_tests_were_not_executed() -> None:
    lowered = developer_prompts.TEST_GENERATION_PROMPT.lower()
    assert "these are proposed tests" in lowered
    assert "have not been executed" in lowered
    assert "never invent an api to test" in lowered


def test_debug_prompt_distinguishes_confidence_levels() -> None:
    lowered = developer_prompts.BUG_ANALYSIS_PROMPT.lower()
    assert "have not reproduced the problem" in lowered
    for level in ("confirmed", "likely", "possible"):
        assert level in lowered
    assert "never invent a stack trace" in lowered


def test_documentation_prompt_forbids_inventing_parameters() -> None:
    prompt = developer_prompts.DOCUMENTATION_PROMPT
    assert "NEVER invent parameters" in prompt
    assert "Not determinable from the supplied code." in prompt


# --- Prompt regression: required context reaches the model ------------------


def test_generation_prompt_carries_language_description_and_requirements(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.generate_code(
        "typescript", "Validate an email address", ["No regex", "Return a boolean"]
    )

    prompt = recorded_generate.user_prompt
    assert "typescript" in prompt
    assert "Validate an email address" in prompt
    assert "No regex" in prompt
    assert "Return a boolean" in prompt


def test_review_prompt_carries_code_and_focus_areas(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.review_code(
        LANG, CODE, [ReviewFocus.SECURITY, ReviewFocus.PERFORMANCE]
    )

    prompt = recorded_generate.user_prompt
    assert CODE in prompt
    assert developer_prompts.REVIEW_FOCUS_GUIDANCE[ReviewFocus.SECURITY] in prompt
    assert developer_prompts.REVIEW_FOCUS_GUIDANCE[ReviewFocus.PERFORMANCE] in prompt


def test_review_without_focus_asks_for_everything(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.review_code(LANG, CODE, [])

    assert "Review all aspects" in recorded_generate.user_prompt


def test_refactor_prompt_supplies_default_goals_when_none_given(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.refactor_code(LANG, CODE, [])

    assert "Improve readability" in recorded_generate.user_prompt


def test_test_prompt_carries_the_requested_framework(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.generate_tests(LANG, CODE, "pytest")

    assert "pytest" in recorded_generate.user_prompt


def test_test_prompt_handles_an_unspecified_framework(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.generate_tests(LANG, CODE, None)

    assert "not specified" in recorded_generate.user_prompt


def test_debug_prompt_carries_error_and_context(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.analyse_bug(
        LANG, CODE, "IndexError: list index out of range", "Happens on empty input."
    )

    prompt = recorded_generate.user_prompt
    assert "IndexError: list index out of range" in prompt
    assert "Happens on empty input." in prompt


def test_debug_prompt_notes_when_no_error_was_supplied(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.analyse_bug(LANG, CODE, None, None)

    assert "none supplied" in recorded_generate.user_prompt


def test_documentation_prompt_carries_the_requested_type(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.generate_documentation(LANG, CODE, DocumentationType.README)

    assert (
        developer_prompts.DOCUMENTATION_TYPE_GUIDANCE[DocumentationType.README]
        in recorded_generate.user_prompt
    )


# --- Sampling strategy ------------------------------------------------------


def test_developer_temperatures_are_low_and_task_specific(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "{}"

    developer_agent.generate_code(LANG, "Add numbers")
    assert recorded_generate.last["temperature"] == TEMPERATURE_GENERATION

    developer_agent.review_code(LANG, CODE)
    assert recorded_generate.last["temperature"] == TEMPERATURE_REVIEW

    developer_agent.analyse_bug(LANG, CODE, "TypeError")
    assert recorded_generate.last["temperature"] == TEMPERATURE_DEBUG

    # Analysis must be more deterministic than writing new code.
    assert TEMPERATURE_REVIEW < TEMPERATURE_GENERATION


def test_all_developer_temperatures_are_below_content_generation() -> None:
    """Code analysis should never be as loose as creative writing."""
    from app.agents import content_agent as content
    from app.agents import developer_agent as dev

    developer_temps = [
        dev.TEMPERATURE_GENERATION,
        dev.TEMPERATURE_EXPLANATION,
        dev.TEMPERATURE_REVIEW,
        dev.TEMPERATURE_REFACTOR,
        dev.TEMPERATURE_TESTS,
        dev.TEMPERATURE_DEBUG,
        dev.TEMPERATURE_DOCUMENTATION,
    ]
    assert max(developer_temps) < content.TEMPERATURE_GENERATION


# --- Structured output parsing ----------------------------------------------


def test_review_parses_a_full_payload(recorded_generate: GenerateRecorder) -> None:
    recorded_generate.content = _json(
        {
            "overall_assessment": "Reasonable but unvalidated.",
            "issues": [
                {
                    "severity": "high",
                    "category": "bugs",
                    "line": 2,
                    "problem": "No type checking.",
                    "recommendation": "Validate inputs.",
                }
            ],
            "positive_points": ["Clear naming."],
            "summary": "Add validation.",
        }
    )

    result = developer_agent.review_code(LANG, CODE)

    assert result.task_type == "code_review"
    assert result.data["issues"][0]["severity"] == "high"
    assert result.data["issues"][0]["line"] == 2
    assert result.data["positive_points"] == ["Clear naming."]


def test_missing_keys_become_empty_sections(
    recorded_generate: GenerateRecorder,
) -> None:
    """A partial response is degraded, not fatal."""
    recorded_generate.content = _json({"summary": "It adds two numbers."})

    result = developer_agent.explain_code(LANG, CODE)

    assert result.data["summary"] == "It adds two numbers."
    assert result.data["line_by_line_explanation"] == []
    assert result.data["potential_issues"] == []


@pytest.mark.parametrize(
    "bad_output",
    ["not json at all", '{"issues": [broken]}', "[1,2,3]", "   "],
    ids=["prose", "malformed", "array", "blank"],
)
def test_malformed_output_raises_ai_invalid_output(
    recorded_generate: GenerateRecorder, bad_output: str
) -> None:
    recorded_generate.content = bad_output

    with pytest.raises(AppError) as exc_info:
        developer_agent.review_code(LANG, CODE)

    assert exc_info.value.code == "AI_INVALID_OUTPUT"
    assert exc_info.value.status_code == 502


def test_json_wrapped_in_code_fences_is_recovered(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = '```json\n{"summary": "Adds numbers."}\n```'

    result = developer_agent.explain_code(LANG, CODE)

    assert result.data["summary"] == "Adds numbers."


# --- Anti-fabrication: line numbers -----------------------------------------


def test_line_numbers_beyond_the_source_are_discarded(
    recorded_generate: GenerateRecorder,
) -> None:
    """CODE has 3 lines, so line 87 is fabricated and must not be reported."""
    recorded_generate.content = _json(
        {
            "issues": [
                {"severity": "high", "line": 2, "problem": "real"},
                {"severity": "low", "line": 87, "problem": "fabricated"},
            ]
        }
    )

    result = developer_agent.review_code(LANG, CODE)

    assert result.data["issues"][0]["line"] == 2
    assert result.data["issues"][1]["line"] is None


@pytest.mark.parametrize(
    ("raw_line", "expected"),
    [
        (0, None),
        (-5, None),
        ("2", 2),
        ("line 2", 2),
        ("unknown", None),
        (None, None),
        (True, None),
        (2.0, 2),
    ],
    ids=["zero", "negative", "numeric-string", "prefixed", "prose", "null", "bool", "float"],
)
def test_implausible_line_values_become_null(
    recorded_generate: GenerateRecorder, raw_line: object, expected: int | None
) -> None:
    recorded_generate.content = _json(
        {"issues": [{"severity": "low", "line": raw_line, "problem": "x"}]}
    )

    result = developer_agent.review_code(LANG, CODE)

    assert result.data["issues"][0]["line"] == expected


# --- Anti-fabrication: severity ---------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CRITICAL", "critical"),
        ("major", "high"),
        ("warning", "medium"),
        ("nit", "low"),
        ("suggestion", "info"),
        ("wildly-made-up", "info"),
        (42, "info"),
    ],
)
def test_severity_is_normalised_without_inflating_risk(
    recorded_generate: GenerateRecorder, raw: object, expected: str
) -> None:
    recorded_generate.content = _json(
        {"issues": [{"severity": raw, "problem": "x"}]}
    )

    result = developer_agent.review_code(LANG, CODE)

    assert result.data["issues"][0]["severity"] == expected


def test_non_object_issues_are_dropped(recorded_generate: GenerateRecorder) -> None:
    recorded_generate.content = _json(
        {"issues": ["just a string", None, {"severity": "low", "problem": "real"}]}
    )

    result = developer_agent.review_code(LANG, CODE)

    assert len(result.data["issues"]) == 1
    assert result.data["issues"][0]["problem"] == "real"


# --- Anti-fabrication: test execution claims --------------------------------


def test_test_generation_marks_output_as_unexecuted(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = _json(
        {"framework": "pytest", "test_code": "def test_add(): assert add(1,2)==3"}
    )

    result = developer_agent.generate_tests(LANG, CODE, "pytest")

    assert result.data["executed"] is False
    assert "have not been executed" in result.data["disclaimer"]


# --- Anti-fabrication: debug confidence -------------------------------------


def test_confirmed_is_downgraded_when_no_error_was_supplied(
    recorded_generate: GenerateRecorder,
) -> None:
    """Reasoning from code alone cannot justify "confirmed"."""
    recorded_generate.content = _json(
        {"problem": "Crash", "confidence": "confirmed", "likely_cause": "No guard"}
    )

    result = developer_agent.analyse_bug(LANG, CODE, error_message=None)

    assert result.data["confidence"] == "likely"


def test_confirmed_is_kept_when_an_error_was_supplied(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = _json({"confidence": "confirmed"})

    result = developer_agent.analyse_bug(LANG, CODE, error_message="TypeError: ...")

    assert result.data["confidence"] == "confirmed"


@pytest.mark.parametrize(
    "raw", ["certain", "definitely", "", 5, "PROVEN"]
)
def test_unknown_confidence_defaults_to_the_weakest_claim(
    recorded_generate: GenerateRecorder, raw: object
) -> None:
    recorded_generate.content = _json({"confidence": raw})

    result = developer_agent.analyse_bug(LANG, CODE, "TypeError")

    assert result.data["confidence"] == "possible"


# --- Code fence normalisation -----------------------------------------------


@pytest.mark.parametrize(
    ("task", "field", "payload_key"),
    [
        ("generate", "code", "code"),
        ("refactor", "refactored_code", "refactored_code"),
        ("tests", "test_code", "test_code"),
        ("debug", "fixed_code", "fixed_code"),
    ],
)
def test_code_fields_are_returned_without_markdown_fences(
    recorded_generate: GenerateRecorder, task: str, field: str, payload_key: str
) -> None:
    """The API returns editor-ready code, not markdown."""
    recorded_generate.content = _json({field: "```python\ndef add(a, b):\n    return a + b\n```"})

    runners = {
        "generate": lambda: developer_agent.generate_code(LANG, "Add"),
        "refactor": lambda: developer_agent.refactor_code(LANG, CODE),
        "tests": lambda: developer_agent.generate_tests(LANG, CODE),
        "debug": lambda: developer_agent.analyse_bug(LANG, CODE, "err"),
    }
    result = runners[task]()

    code = result.data[payload_key]
    assert not code.startswith("```")
    assert not code.endswith("```")
    assert code == "def add(a, b):\n    return a + b"


def test_generation_reports_the_requested_language(
    recorded_generate: GenerateRecorder,
) -> None:
    """The request is authoritative, not whatever the model echoed."""
    recorded_generate.content = _json({"language": "Python 3.11", "code": "pass"})

    result = developer_agent.generate_code("go", "Do something")

    assert result.data["language"] == "go"


def test_documentation_reports_the_requested_type(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = _json({"summary": "A function."})

    result = developer_agent.generate_documentation(
        LANG, CODE, DocumentationType.API
    )

    assert result.data["documentation_type"] == "api"


# --- Provider failures propagate --------------------------------------------


def test_provider_errors_are_not_swallowed(failing_generate: GenerateRecorder) -> None:
    with pytest.raises(AppError) as exc_info:
        developer_agent.review_code(LANG, CODE)

    assert exc_info.value.code == "AI_PROVIDER_ERROR"
