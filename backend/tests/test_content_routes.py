"""Phase 5 tests: the /api/content/* HTTP contract.

Validation, envelopes and status codes, with the AI call faked out.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.content_schemas import MAX_TEXT_CHARS, MAX_TOPIC_CHARS
from tests.conftest import GenerateRecorder

client = TestClient(app)

# Phase 10 protects these routes. These tests cover behaviour, not
# authentication, so they run as a signed-in user. Protection itself is
# verified in test_route_protection.py against the real dependency.
pytestmark = pytest.mark.usefixtures("authenticated")

SOURCE = "Acme Corp released Widget 3 in March 2024. It cut processing time by 40%."

VALID_GENERATE = {
    "topic": "Artificial Intelligence in Education",
    "content_type": "blog",
    "tone": "professional",
    "audience": "student",
    "length": "medium",
    "additional_instructions": "Use simple examples.",
}

# Every text-producing endpoint with a minimal valid body.
TEXT_ENDPOINTS = [
    ("/api/content/generate", VALID_GENERATE, "generation"),
    ("/api/content/summarize", {"text": SOURCE, "summary_type": "short"}, "summarization"),
    ("/api/content/rewrite", {"text": SOURCE, "instructions": "Clearer."}, "rewrite"),
    ("/api/content/tone", {"text": SOURCE, "tone": "casual"}, "tone_transformation"),
    ("/api/content/audience", {"text": SOURCE, "audience": "beginner"}, "audience_adaptation"),
    ("/api/content/format", {"text": SOURCE, "format": "bullet_points"}, "format_transformation"),
]


# --- Success envelopes ------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "payload", "task_type"),
    TEXT_ENDPOINTS,
    ids=[e.rsplit("/", 1)[-1] for e, _, _ in TEXT_ENDPOINTS],
)
def test_endpoints_return_the_standard_success_envelope(
    recorded_generate: GenerateRecorder, endpoint: str, payload: dict, task_type: str
) -> None:
    recorded_generate.content = "Some produced text."

    response = client.post(endpoint, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"success", "message", "data"}
    assert body["success"] is True
    assert body["data"]["content"] == "Some produced text."
    assert body["data"]["task_type"] == task_type
    assert body["data"]["model"]
    assert body["data"]["usage"]["total_tokens"] == 100


def test_all_content_endpoints_appear_in_openapi() -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for endpoint in (
        "/api/content/generate",
        "/api/content/summarize",
        "/api/content/rewrite",
        "/api/content/tone",
        "/api/content/audience",
        "/api/content/format",
        "/api/content/extract",
    ):
        assert endpoint in paths, endpoint
        assert "post" in paths[endpoint]
        assert paths[endpoint]["post"]["summary"]


# --- Generation validation --------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"topic": ""},
        {"topic": "   "},
        {"topic": None},
    ],
    ids=["missing", "empty", "whitespace", "null"],
)
def test_generate_rejects_bad_topics(
    recorded_generate: GenerateRecorder, payload: dict
) -> None:
    response = client.post("/api/content/generate", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_generate_rejects_unsupported_content_type(
    recorded_generate: GenerateRecorder,
) -> None:
    response = client.post(
        "/api/content/generate", json={"topic": "AI", "content_type": "haiku"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "content_type"


def test_generate_rejects_oversized_topic(recorded_generate: GenerateRecorder) -> None:
    response = client.post(
        "/api/content/generate", json={"topic": "a" * (MAX_TOPIC_CHARS + 1)}
    )

    assert response.status_code == 422


def test_generate_applies_documented_defaults(
    recorded_generate: GenerateRecorder,
) -> None:
    """Only `topic` is required; the rest have sensible defaults."""
    response = client.post("/api/content/generate", json={"topic": "AI"})

    assert response.status_code == 200
    prompt = recorded_generate.user_prompt
    assert "blog" in prompt or "blog post" in prompt


# --- Shared text validation across the transformation endpoints -------------


@pytest.mark.parametrize(
    ("endpoint", "extra"),
    [
        ("/api/content/summarize", {"summary_type": "short"}),
        ("/api/content/rewrite", {"instructions": "Clearer."}),
        ("/api/content/tone", {"tone": "formal"}),
        ("/api/content/audience", {"audience": "beginner"}),
        ("/api/content/format", {"format": "report"}),
        ("/api/content/extract", {}),
    ],
    ids=["summarize", "rewrite", "tone", "audience", "format", "extract"],
)
@pytest.mark.parametrize(
    "text_value", ["", "   ", None], ids=["empty", "whitespace", "null"]
)
def test_endpoints_reject_empty_text(
    recorded_generate: GenerateRecorder,
    endpoint: str,
    extra: dict,
    text_value: object,
) -> None:
    response = client.post(endpoint, json={"text": text_value, **extra})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("endpoint", "extra"),
    [
        ("/api/content/summarize", {"summary_type": "short"}),
        ("/api/content/tone", {"tone": "formal"}),
        ("/api/content/extract", {}),
    ],
    ids=["summarize", "tone", "extract"],
)
def test_endpoints_reject_oversized_text(
    recorded_generate: GenerateRecorder, endpoint: str, extra: dict
) -> None:
    """Unlimited input must never reach the provider."""
    response = client.post(
        endpoint, json={"text": "a" * (MAX_TEXT_CHARS + 1), **extra}
    )

    assert response.status_code == 422


def test_text_is_stripped_before_reaching_the_agent(
    recorded_generate: GenerateRecorder,
) -> None:
    client.post(
        "/api/content/summarize",
        json={"text": f"   {SOURCE}   ", "summary_type": "short"},
    )

    assert f'"""\n{SOURCE}\n"""' in recorded_generate.user_prompt


# --- Controlled vocabularies ------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "payload", "bad_field"),
    [
        ("/api/content/summarize", {"text": SOURCE, "summary_type": "tweet"}, "summary_type"),
        ("/api/content/tone", {"text": SOURCE, "tone": "sarcastic"}, "tone"),
        ("/api/content/audience", {"text": SOURCE, "audience": "aliens"}, "audience"),
        ("/api/content/format", {"text": SOURCE, "format": "powerpoint"}, "format"),
    ],
    ids=["summary_type", "tone", "audience", "format"],
)
def test_unsupported_values_are_rejected(
    recorded_generate: GenerateRecorder, endpoint: str, payload: dict, bad_field: str
) -> None:
    response = client.post(endpoint, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == bad_field


@pytest.mark.parametrize(
    "tone",
    ["professional", "formal", "friendly", "casual", "persuasive", "simple", "academic"],
)
def test_every_documented_tone_is_accepted(
    recorded_generate: GenerateRecorder, tone: str
) -> None:
    response = client.post("/api/content/tone", json={"text": SOURCE, "tone": tone})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "audience",
    ["beginner", "student", "developer", "technical_professional", "general_audience", "executive"],
)
def test_every_documented_audience_is_accepted(
    recorded_generate: GenerateRecorder, audience: str
) -> None:
    response = client.post(
        "/api/content/audience", json={"text": SOURCE, "audience": audience}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "content_format",
    ["paragraph", "bullet_points", "article", "email", "report", "social_media"],
)
def test_every_documented_format_is_accepted(
    recorded_generate: GenerateRecorder, content_format: str
) -> None:
    response = client.post(
        "/api/content/format", json={"text": SOURCE, "format": content_format}
    )

    assert response.status_code == 200


@pytest.mark.parametrize("summary_type", ["short", "detailed", "bullet_points"])
def test_every_documented_summary_type_is_accepted(
    recorded_generate: GenerateRecorder, summary_type: str
) -> None:
    response = client.post(
        "/api/content/summarize", json={"text": SOURCE, "summary_type": summary_type}
    )

    assert response.status_code == 200


def test_rewrite_requires_instructions(recorded_generate: GenerateRecorder) -> None:
    response = client.post("/api/content/rewrite", json={"text": SOURCE})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "instructions"


# --- Extraction endpoint ----------------------------------------------------


def test_extract_returns_the_structured_payload(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = json.dumps(
        {
            "entities": ["Acme Corp"],
            "key_points": ["Widget 3 shipped."],
            "facts": ["Processing time fell 40%."],
            "keywords": ["widget"],
        }
    )

    response = client.post("/api/content/extract", json={"text": SOURCE})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["entities"] == ["Acme Corp"]
    assert data["key_points"] == ["Widget 3 shipped."]
    assert data["facts"] == ["Processing time fell 40%."]
    assert data["keywords"] == ["widget"]
    assert data["task_type"] == "extraction"


def test_extract_reports_malformed_model_output_as_an_error(
    recorded_generate: GenerateRecorder,
) -> None:
    recorded_generate.content = "The model ignored the JSON instruction entirely."

    response = client.post("/api/content/extract", json={"text": SOURCE})

    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "AI_INVALID_OUTPUT"


# --- Provider failures reuse the existing error system ----------------------


def test_provider_failure_returns_the_standard_error_envelope(
    failing_generate: GenerateRecorder,
) -> None:
    response = client.post(
        "/api/content/summarize", json={"text": SOURCE, "summary_type": "short"}
    )

    assert response.status_code == 502
    assert response.json() == {
        "success": False,
        "message": "AI service is temporarily unavailable",
        "error": {"code": "AI_PROVIDER_ERROR", "details": None},
    }


def test_missing_api_key_surfaces_as_service_unavailable(
    groq_unconfigured: None,
) -> None:
    """With no key configured, content endpoints fail the same way /ai/test does."""
    response = client.post(
        "/api/content/summarize", json={"text": SOURCE, "summary_type": "short"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"


def test_content_endpoints_never_touch_the_database(
    recorded_generate: GenerateRecorder,
) -> None:
    """Phase 5 must work with no MongoDB connection at all."""
    from app.database import mongodb

    mongodb._client = None
    mongodb._connected = False

    response = client.post(
        "/api/content/rewrite", json={"text": SOURCE, "instructions": "Clearer."}
    )

    assert response.status_code == 200
