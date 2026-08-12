"""Developer Productivity Agent endpoints.

Thin by design: validate, call one agent method, wrap in the standard
envelope. No prompt construction, no Groq SDK, no database.

User-supplied code is never executed here or anywhere downstream — it is
treated purely as text to put in a prompt.
"""

from fastapi import APIRouter

from app.agents.developer_agent import DeveloperResult, developer_agent
from app.schemas.common_schemas import SuccessResponse, success
from app.schemas.developer_schemas import (
    BugAnalysisRequest,
    CodeExplanationRequest,
    CodeGenerationRequest,
    CodeRefactorRequest,
    CodeReviewRequest,
    DocumentationRequest,
    TestGenerationRequest,
)

router = APIRouter(tags=["Developer Agent"])


def _payload(result: DeveloperResult) -> dict:
    """Shape an agent result into the `data` field.

    The structured payload is spread at the top level so clients read
    `data.issues` rather than `data.data.issues`.
    """
    return {**result.data, "task_type": result.task_type, "model": result.model,
            "usage": result.usage}


@router.post(
    "/generate",
    response_model=SuccessResponse,
    summary="Generate code from a description",
    description=(
        "Writes code in the requested language satisfying the description and "
        "requirements. Returns clean code with markdown fences removed, plus "
        "an explanation, assumptions and known limitations. The generated code "
        "is not executed or verified."
    ),
)
def generate_code(request: CodeGenerationRequest) -> dict:
    result = developer_agent.generate_code(
        language=request.language,
        description=request.description,
        requirements=request.requirements,
    )
    return success(data=_payload(result), message="Code generated successfully")


@router.post(
    "/explain",
    response_model=SuccessResponse,
    summary="Explain supplied code",
    description=(
        "Returns a summary, a step-by-step walkthrough, important concepts and "
        "any genuine problems visible in the supplied code."
    ),
)
def explain_code(request: CodeExplanationRequest) -> dict:
    result = developer_agent.explain_code(
        language=request.language, code=request.code
    )
    return success(data=_payload(result), message="Code explained successfully")


@router.post(
    "/review",
    response_model=SuccessResponse,
    summary="Review supplied code",
    description=(
        "Returns severity-rated findings (critical / high / medium / low / "
        "info). Line numbers that do not exist in the submitted code are "
        "discarded rather than reported."
    ),
)
def review_code(request: CodeReviewRequest) -> dict:
    result = developer_agent.review_code(
        language=request.language,
        code=request.code,
        review_focus=request.review_focus,
    )
    return success(data=_payload(result), message="Code reviewed successfully")


@router.post(
    "/refactor",
    response_model=SuccessResponse,
    summary="Refactor supplied code",
    description=(
        "Restructures the code toward the stated goals while preserving its "
        "intended behaviour. Returns the refactored code, the changes made, "
        "the reasoning and the trade-offs."
    ),
)
def refactor_code(request: CodeRefactorRequest) -> dict:
    result = developer_agent.refactor_code(
        language=request.language, code=request.code, goals=request.goals
    )
    return success(data=_payload(result), message="Code refactored successfully")


@router.post(
    "/tests",
    response_model=SuccessResponse,
    summary="Generate test cases for supplied code",
    description=(
        "Proposes tests covering normal, boundary, invalid, empty and error "
        "cases where relevant. These tests are NOT executed by this system; "
        "the response carries an explicit disclaimer saying so."
    ),
)
def generate_tests(request: TestGenerationRequest) -> dict:
    result = developer_agent.generate_tests(
        language=request.language, code=request.code, framework=request.framework
    )
    return success(data=_payload(result), message="Tests generated successfully")


@router.post(
    "/debug",
    response_model=SuccessResponse,
    summary="Analyse a bug in supplied code",
    description=(
        "Diagnoses the likely cause from the code and any supplied error. "
        "Reports confidence as confirmed / likely / possible, and separates "
        "observed evidence from reasoning. The bug is not reproduced."
    ),
)
def analyse_bug(request: BugAnalysisRequest) -> dict:
    result = developer_agent.analyse_bug(
        language=request.language,
        code=request.code,
        error_message=request.error_message,
        context=request.context,
    )
    return success(data=_payload(result), message="Bug analysis completed")


@router.post(
    "/document",
    response_model=SuccessResponse,
    summary="Generate documentation for supplied code",
    description=(
        "Produces function, module, API, README or technical documentation. "
        "Anything not determinable from the supplied code is reported as such "
        "rather than invented."
    ),
)
def generate_documentation(request: DocumentationRequest) -> dict:
    result = developer_agent.generate_documentation(
        language=request.language,
        code=request.code,
        documentation_type=request.documentation_type,
    )
    return success(data=_payload(result), message="Documentation generated successfully")
