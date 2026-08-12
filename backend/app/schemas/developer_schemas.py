"""Request and response models for the Developer Productivity Agent.

A note on language handling. Tone and audience are closed sets — the agent
genuinely only supports six audiences. Programming languages are not: a
hard enum would mean a code change every time someone pastes Elixir or Scala,
and rejecting valid code because the enum is short is a worse failure than
passing an unfamiliar language name to the model.

So `language` is a validated, normalised string rather than an enum, with
COMMON_LANGUAGES used for documentation and Swagger examples. The other three
vocabularies (severity, review focus, documentation type) are genuinely
closed and stay as enums.
"""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

# --- Input limits -----------------------------------------------------------
#
# Code gets 30,000 characters (~7,500 tokens) — larger than the 20,000 allowed
# for prose in Phase 5, because source files are denser and a reviewer needs
# the whole file to judge it. Free-text fields are smaller, and list fields
# are capped on BOTH item count and per-item length: 20 unbounded requirements
# would defeat the point of having a limit at all.
MAX_CODE_CHARS = 30_000
MAX_DESCRIPTION_CHARS = 5_000
MAX_ERROR_MESSAGE_CHARS = 5_000
MAX_CONTEXT_CHARS = 10_000
MAX_LIST_ITEMS = 20
MAX_LIST_ITEM_CHARS = 300
MAX_LANGUAGE_CHARS = 30

CodeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CODE_CHARS),
]
DescriptionText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_DESCRIPTION_CHARS
    ),
]
ErrorMessageText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_ERROR_MESSAGE_CHARS
    ),
]
ContextText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CONTEXT_CHARS),
]
ListItemText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_LIST_ITEM_CHARS
    ),
]

# Allows "c++", "c#", "objective-c", "f#". Rejects prose, paths and anything
# long enough to be a smuggled instruction.
#
# The pattern accepts both cases even though the value is lowercased: Pydantic
# applies `pattern` BEFORE `to_lower`, so a lowercase-only pattern would reject
# "Python" outright instead of normalising it.
LanguageName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=MAX_LANGUAGE_CHARS,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9+#.\- ]*$",
    ),
]

COMMON_LANGUAGES = (
    "python", "javascript", "typescript", "java", "c", "cpp", "csharp",
    "go", "rust", "php", "ruby", "kotlin", "swift", "sql", "html", "css",
    "bash",
)


# --- Controlled vocabularies ------------------------------------------------


class ReviewSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ReviewFocus(str, Enum):
    BUGS = "bugs"
    SECURITY = "security"
    PERFORMANCE = "performance"
    READABILITY = "readability"
    MAINTAINABILITY = "maintainability"
    ERROR_HANDLING = "error_handling"
    EDGE_CASES = "edge_cases"


class DocumentationType(str, Enum):
    FUNCTION = "function"
    MODULE = "module"
    API = "api"
    README = "readme"
    TECHNICAL = "technical"


# --- Requests ---------------------------------------------------------------


class CodeGenerationRequest(BaseModel):
    """POST /api/developer/generate"""

    language: LanguageName = Field(examples=["python"])
    description: DescriptionText = Field(description="What the code should do.")
    requirements: list[ListItemText] = Field(
        default_factory=list, max_length=MAX_LIST_ITEMS
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "language": "python",
                "description": (
                    "Create a function that checks whether a string is a palindrome."
                ),
                "requirements": ["Use a clean function", "Handle empty strings"],
            }
        }
    }


class CodeExplanationRequest(BaseModel):
    """POST /api/developer/explain"""

    language: LanguageName = Field(examples=["python"])
    code: CodeText


class CodeReviewRequest(BaseModel):
    """POST /api/developer/review"""

    language: LanguageName = Field(examples=["python"])
    code: CodeText
    review_focus: list[ReviewFocus] = Field(
        default_factory=list,
        description="Areas to prioritise. Empty means review everything.",
    )

    @field_validator("review_focus")
    @classmethod
    def deduplicate(cls, value: list[ReviewFocus]) -> list[ReviewFocus]:
        return list(dict.fromkeys(value))


class CodeRefactorRequest(BaseModel):
    """POST /api/developer/refactor"""

    language: LanguageName = Field(examples=["python"])
    code: CodeText
    goals: list[ListItemText] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)


class TestGenerationRequest(BaseModel):
    """POST /api/developer/tests"""

    language: LanguageName = Field(examples=["python"])
    code: CodeText
    framework: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
    ] | None = Field(
        default=None,
        description="Test framework, e.g. pytest. Omit to let the agent choose.",
        examples=["pytest"],
    )


class BugAnalysisRequest(BaseModel):
    """POST /api/developer/debug"""

    language: LanguageName = Field(examples=["python"])
    code: CodeText
    error_message: ErrorMessageText | None = Field(
        default=None, description="The error or stack trace, if there is one."
    )
    context: ContextText | None = Field(
        default=None, description="When and how the problem occurs."
    )


class DocumentationRequest(BaseModel):
    """POST /api/developer/document"""

    language: LanguageName = Field(examples=["python"])
    code: CodeText
    documentation_type: DocumentationType = DocumentationType.FUNCTION


# --- Structured model output ------------------------------------------------
#
# Every field has a default so a missing key yields an empty section rather
# than a failed request. Validation only fails when the shape is genuinely
# wrong, which is what AI_INVALID_OUTPUT is for.


class BugConfidence(str, Enum):
    """How strongly the supplied evidence supports a diagnosis."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    POSSIBLE = "possible"


def _as_list(value: object) -> list[str]:
    """Shared `mode="before"` coercion for list-of-string fields."""
    from app.utils.ai_output import coerce_string_list

    return coerce_string_list(value)


class ReviewIssue(BaseModel):
    """One finding from a code review."""

    severity: ReviewSeverity = ReviewSeverity.INFO
    category: str = "general"
    line: int | None = Field(
        default=None,
        description="1-based line number, or null when it cannot be determined.",
    )
    problem: str = ""
    recommendation: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, value: object) -> str:
        """Map near-miss severities onto the supported set.

        Models return "warning", "major", "MEDIUM" and similar. Failing an
        otherwise-useful review over one label would be the wrong trade; an
        unrecognised value degrades to "info" rather than inflating risk.
        """
        if not isinstance(value, str):
            return ReviewSeverity.INFO.value
        text = value.strip().lower()
        synonyms = {
            "blocker": "critical",
            "severe": "critical",
            "major": "high",
            "error": "high",
            "warning": "medium",
            "moderate": "medium",
            "minor": "low",
            "nit": "low",
            "note": "info",
            "suggestion": "info",
            "informational": "info",
        }
        text = synonyms.get(text, text)
        return text if text in {s.value for s in ReviewSeverity} else "info"

    @field_validator("line", mode="before")
    @classmethod
    def normalise_line(cls, value: object) -> int | None:
        """Accept only a plausible 1-based line number.

        Strings, floats, zero and negatives all become null. The agent
        performs the second check — that the line exists in the submitted
        code — because only it has the code.
        """
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 1 else None
        if isinstance(value, float):
            return int(value) if value >= 1 else None
        if isinstance(value, str):
            digits = value.strip().lstrip("line").strip(": ")
            return int(digits) if digits.isdigit() and int(digits) >= 1 else None
        return None


class ReviewPayload(BaseModel):
    """Structured output of a code review."""

    overall_assessment: str = ""
    issues: list[ReviewIssue] = []
    positive_points: list[str] = []
    summary: str = ""

    _coerce_positive = field_validator("positive_points", mode="before")(_as_list)

    @field_validator("issues", mode="before")
    @classmethod
    def drop_unusable_issues(cls, value: object) -> list:
        """Keep only dict-shaped issues; ignore stray strings or nulls."""
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]


class CodeGenerationPayload(BaseModel):
    """Structured output of code generation."""

    language: str = ""
    code: str = ""
    explanation: str = ""
    usage_example: str = ""
    assumptions: list[str] = []
    limitations: list[str] = []

    _coerce_assumptions = field_validator("assumptions", mode="before")(_as_list)
    _coerce_limitations = field_validator("limitations", mode="before")(_as_list)


class ExplanationPayload(BaseModel):
    """Structured output of code explanation."""

    summary: str = ""
    line_by_line_explanation: list[str] = []
    important_concepts: list[str] = []
    potential_issues: list[str] = []

    _coerce_walkthrough = field_validator(
        "line_by_line_explanation", mode="before"
    )(_as_list)
    _coerce_concepts = field_validator("important_concepts", mode="before")(_as_list)
    _coerce_issues = field_validator("potential_issues", mode="before")(_as_list)


class RefactorPayload(BaseModel):
    """Structured output of a refactor."""

    original_intent: str = ""
    refactored_code: str = ""
    changes: list[str] = []
    reasoning: str = ""
    tradeoffs: list[str] = []

    _coerce_changes = field_validator("changes", mode="before")(_as_list)
    _coerce_tradeoffs = field_validator("tradeoffs", mode="before")(_as_list)


class TestCase(BaseModel):
    """One proposed test case. Proposed — never executed by this system."""

    name: str = ""
    category: str = "normal"
    description: str = ""
    expected_behavior: str = ""


class TestGenerationPayload(BaseModel):
    """Structured output of test generation."""

    framework: str = ""
    test_code: str = ""
    test_cases: list[TestCase] = []
    coverage_notes: str = ""

    @field_validator("test_cases", mode="before")
    @classmethod
    def drop_unusable_cases(cls, value: object) -> list:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]


class BugAnalysisPayload(BaseModel):
    """Structured output of bug analysis."""

    problem: str = ""
    confidence: BugConfidence = BugConfidence.POSSIBLE
    likely_cause: str = ""
    evidence: list[str] = []
    other_possible_causes: list[str] = []
    fix: str = ""
    fixed_code: str = ""
    prevention: list[str] = []

    _coerce_evidence = field_validator("evidence", mode="before")(_as_list)
    _coerce_causes = field_validator("other_possible_causes", mode="before")(_as_list)
    _coerce_prevention = field_validator("prevention", mode="before")(_as_list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalise_confidence(cls, value: object) -> str:
        """Default to the weakest claim when the model says something else.

        Erring toward "possible" is the safe direction: overstating certainty
        about a bug diagnosis is the failure mode that misleads a developer.
        """
        if not isinstance(value, str):
            return BugConfidence.POSSIBLE.value
        text = value.strip().lower()
        return (
            text
            if text in {c.value for c in BugConfidence}
            else BugConfidence.POSSIBLE.value
        )


class DocParameter(BaseModel):
    """One documented parameter."""

    name: str = ""
    type: str = ""
    description: str = ""
    required: bool = True


class DocumentationPayload(BaseModel):
    """Structured output of documentation generation."""

    summary: str = ""
    documentation: str = ""
    usage_example: str = ""
    parameters: list[DocParameter] = []
    returns: str = ""
    exceptions: list[str] = []

    _coerce_exceptions = field_validator("exceptions", mode="before")(_as_list)

    @field_validator("parameters", mode="before")
    @classmethod
    def drop_unusable_parameters(cls, value: object) -> list:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]
