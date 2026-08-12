"""The Developer Productivity Agent.

Seven static-analysis tasks over user-supplied code. Same shape as the
Content Agent: pick the prompt, pick the sampling settings, call the shared
GroqService, validate what comes back.

SECURITY: this agent never executes, compiles, imports or writes the code it
is given. There is no exec, no eval, no subprocess and no filesystem access
anywhere in this module or the ones it calls. User code is a string that gets
put in a prompt and nothing more. Anything that changes that is a serious
regression, and there is a test asserting it.
"""

import logging
from dataclasses import dataclass, field

from app.prompts.developer_prompts import (
    BUG_ANALYSIS_PROMPT,
    CODE_EXPLANATION_PROMPT,
    CODE_GENERATION_PROMPT,
    CODE_REFACTOR_PROMPT,
    CODE_REVIEW_PROMPT,
    DOCUMENTATION_PROMPT,
    TEST_GENERATION_PROMPT,
    build_bug_analysis_prompt,
    build_code_generation_prompt,
    build_documentation_prompt,
    build_explanation_prompt,
    build_refactor_prompt,
    build_review_prompt,
    build_test_generation_prompt,
)
from app.schemas.developer_schemas import (
    BugAnalysisPayload,
    CodeGenerationPayload,
    DocumentationPayload,
    DocumentationType,
    ExplanationPayload,
    RefactorPayload,
    ReviewFocus,
    ReviewPayload,
    TestGenerationPayload,
)
from app.services.groq_service import groq_service
from app.utils.ai_output import parse_structured, strip_code_fences

logger = logging.getLogger("app.agents.developer")


# --- Sampling strategy ------------------------------------------------------
#
# Every value here is lower than the Content Agent's, and deliberately so.
# Creative writing benefits from variation; code analysis does not. A review
# that reports different findings on each run is not a review you can act on,
# and a "creative" line number is a fabricated one.
TEMPERATURE_GENERATION = 0.35
TEMPERATURE_EXPLANATION = 0.20
TEMPERATURE_REVIEW = 0.15
TEMPERATURE_REFACTOR = 0.25
TEMPERATURE_TESTS = 0.25
TEMPERATURE_DEBUG = 0.15
TEMPERATURE_DOCUMENTATION = 0.25

# Code-bearing responses need room: a refactor returns the whole file back,
# plus explanation. Analysis-only tasks need less.
MAX_TOKENS_CODE_HEAVY = 4000
MAX_TOKENS_ANALYSIS = 3000


@dataclass
class DeveloperResult:
    """What the agent hands back to a route.

    `data` holds the validated structured payload. `content` keeps the raw
    model text so a caller can fall back to it, matching the Content Agent's
    result shape.
    """

    task_type: str
    model: str
    data: dict
    usage: dict[str, int] = field(default_factory=dict)
    content: str = ""


class DeveloperAgent:
    """Performs the seven developer tasks."""

    def __init__(self) -> None:
        self._ai = groq_service

    # --- Shared plumbing ----------------------------------------------------

    def _run_structured(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        payload_model: type,
        temperature: float,
        max_tokens: int = MAX_TOKENS_ANALYSIS,
    ) -> DeveloperResult:
        """Run one task and validate its structured output.

        Every task returns JSON, so parsing and validation are defined once.
        JSON mode constrains the provider; parse_structured still treats the
        result as untrusted.
        """
        logger.info(
            "Developer task '%s' starting (temperature=%s)", task_type, temperature
        )

        result = self._ai.generate(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )

        payload = parse_structured(payload_model, result.content, task_type)

        logger.info("Developer task '%s' completed", task_type)

        return DeveloperResult(
            task_type=task_type,
            model=result.model,
            data=payload.model_dump(mode="json"),
            usage=result.usage,
            content=result.content,
        )

    @staticmethod
    def _clean_code_fields(data: dict, *fields: str) -> dict:
        """Strip markdown fences from code-bearing fields.

        Models wrap code in ```python fences even inside a JSON string. The
        API should return code the frontend can drop straight into an editor,
        so the fences come off here rather than in the browser.
        """
        for name in fields:
            value = data.get(name)
            if isinstance(value, str) and value:
                data[name] = strip_code_fences(value)
        return data

    @staticmethod
    def _discard_impossible_line_numbers(data: dict, code: str) -> dict:
        """Null out any line number that does not exist in the submitted code.

        The prompt tells the model not to invent line numbers. This enforces
        it: a citation pointing past the end of the file is fabricated, and a
        wrong line number is worse than none because a developer will trust it
        and look in the wrong place.
        """
        line_count = len(code.splitlines()) or 1
        discarded = 0

        for issue in data.get("issues", []):
            line = issue.get("line")
            if isinstance(line, int) and line > line_count:
                issue["line"] = None
                discarded += 1

        if discarded:
            logger.warning(
                "Discarded %d review line number(s) beyond the %d-line source",
                discarded,
                line_count,
            )
        return data

    # --- Tasks --------------------------------------------------------------

    def generate_code(
        self, language: str, description: str, requirements: list[str] | None = None
    ) -> DeveloperResult:
        """Write new code from a description and a list of requirements."""
        result = self._run_structured(
            task_type="code_generation",
            system_prompt=CODE_GENERATION_PROMPT,
            user_prompt=build_code_generation_prompt(
                language=language,
                description=description,
                requirements=requirements or [],
            ),
            payload_model=CodeGenerationPayload,
            temperature=TEMPERATURE_GENERATION,
            max_tokens=MAX_TOKENS_CODE_HEAVY,
        )
        self._clean_code_fields(result.data, "code", "usage_example")

        # The model occasionally echoes a different label; the request is
        # the authority on what language was asked for.
        result.data["language"] = language
        return result

    def explain_code(self, language: str, code: str) -> DeveloperResult:
        """Explain what supplied code does. Grounded in that code only."""
        return self._run_structured(
            task_type="code_explanation",
            system_prompt=CODE_EXPLANATION_PROMPT,
            user_prompt=build_explanation_prompt(language, code),
            payload_model=ExplanationPayload,
            temperature=TEMPERATURE_EXPLANATION,
        )

    def review_code(
        self, language: str, code: str, review_focus: list[ReviewFocus] | None = None
    ) -> DeveloperResult:
        """Review supplied code and report severity-rated findings."""
        result = self._run_structured(
            task_type="code_review",
            system_prompt=CODE_REVIEW_PROMPT,
            user_prompt=build_review_prompt(language, code, review_focus or []),
            payload_model=ReviewPayload,
            temperature=TEMPERATURE_REVIEW,
        )
        self._discard_impossible_line_numbers(result.data, code)
        return result

    def refactor_code(
        self, language: str, code: str, goals: list[str] | None = None
    ) -> DeveloperResult:
        """Restructure supplied code while preserving its behaviour."""
        result = self._run_structured(
            task_type="code_refactor",
            system_prompt=CODE_REFACTOR_PROMPT,
            user_prompt=build_refactor_prompt(language, code, goals or []),
            payload_model=RefactorPayload,
            temperature=TEMPERATURE_REFACTOR,
            max_tokens=MAX_TOKENS_CODE_HEAVY,
        )
        self._clean_code_fields(result.data, "refactored_code")
        return result

    def generate_tests(
        self, language: str, code: str, framework: str | None = None
    ) -> DeveloperResult:
        """Propose tests for supplied code.

        Proposed, not verified — this system never runs them, and the prompt
        forbids claiming otherwise.
        """
        result = self._run_structured(
            task_type="test_generation",
            system_prompt=TEST_GENERATION_PROMPT,
            user_prompt=build_test_generation_prompt(language, code, framework),
            payload_model=TestGenerationPayload,
            temperature=TEMPERATURE_TESTS,
            max_tokens=MAX_TOKENS_CODE_HEAVY,
        )
        self._clean_code_fields(result.data, "test_code")

        # Stated in the response itself so it survives into any UI that
        # renders the payload without reading our docs.
        result.data["executed"] = False
        result.data["disclaimer"] = (
            "These tests were generated by an AI model and have not been "
            "executed or verified by this system."
        )
        return result

    def analyse_bug(
        self,
        language: str,
        code: str,
        error_message: str | None = None,
        context: str | None = None,
    ) -> DeveloperResult:
        """Diagnose a defect from code and any supplied error information."""
        result = self._run_structured(
            task_type="bug_analysis",
            system_prompt=BUG_ANALYSIS_PROMPT,
            user_prompt=build_bug_analysis_prompt(
                language, code, error_message, context
            ),
            payload_model=BugAnalysisPayload,
            temperature=TEMPERATURE_DEBUG,
            max_tokens=MAX_TOKENS_CODE_HEAVY,
        )
        self._clean_code_fields(result.data, "fixed_code")

        # Without an error message the model is reasoning from code alone, so
        # "confirmed" is not a claim it is entitled to make.
        if not error_message and result.data.get("confidence") == "confirmed":
            logger.info("Downgrading confidence: no error message was supplied")
            result.data["confidence"] = "likely"

        return result

    def generate_documentation(
        self, language: str, code: str, documentation_type: DocumentationType
    ) -> DeveloperResult:
        """Document supplied code, without inventing what is not there."""
        result = self._run_structured(
            task_type="documentation",
            system_prompt=DOCUMENTATION_PROMPT,
            user_prompt=build_documentation_prompt(language, code, documentation_type),
            payload_model=DocumentationPayload,
            temperature=TEMPERATURE_DOCUMENTATION,
        )
        self._clean_code_fields(result.data, "usage_example")
        result.data["documentation_type"] = documentation_type.value
        return result


# Single shared instance, matching the mongodb / groq_service / content_agent
# pattern.
developer_agent = DeveloperAgent()
