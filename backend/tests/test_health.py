"""Tests for the application shell and the /api/health endpoint.

TestClient runs the real FastAPI app in-process — no server needs to be
running, and no network calls are made.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FakeMongoClient

client = TestClient(app)


# --- Phase 2: application shell ---------------------------------------------


def test_app_imports_and_has_metadata() -> None:
    """The application object can be imported without errors."""
    assert app.title
    assert app.version


def test_health_returns_ok(unconfigured_db: None) -> None:
    """GET /api/health returns 200 with success=True and status ok."""
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


def test_health_response_structure(unconfigured_db: None) -> None:
    """The response matches the common success envelope.

    `ai` was added in Phase 12 so a monitor can see provider readiness, not
    only database readiness. This assertion is updated deliberately — the
    contract changed; the test was not weakened.
    """
    body = client.get("/api/health").json()

    assert set(body.keys()) == {"success", "message", "data"}
    assert set(body["data"].keys()) == {
        "status", "service", "version", "database", "ai",
    }
    assert isinstance(body["message"], str)


def test_health_does_not_leak_secrets(connected_db: FakeMongoClient) -> None:
    """The health payload must never echo configuration secrets."""
    raw = client.get("/api/health").text.lower()

    for secret_name in (
        "groq_api_key",
        "mongodb_uri",
        "jwt_secret",
        "password",
        "mongodb+srv",
        "fake-cluster",
        "fake-user",
    ):
        assert secret_name not in raw


def test_unknown_route_uses_error_envelope() -> None:
    """A 404 flows through our handler, not Starlette's default shape."""
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_malformed_json_body_names_the_body_not_an_offset() -> None:
    """Pydantic reports a character offset for unparseable JSON.

    Passing that through as `field: "103"` would be meaningless to a client.
    """
    # A public POST endpoint, so the malformed body is what fails —
    # not authentication, which would otherwise reject the request first.
    response = client.post(
        "/api/auth/login",
        content='{"email": "unterminated',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    detail = response.json()["error"]["details"][0]
    assert detail["field"] == "body"


def test_openapi_schema_is_available() -> None:
    """Swagger's underlying schema is served and includes the health route."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_cors_headers_present_for_allowed_origin(unconfigured_db: None) -> None:
    """The React dev origin is echoed back by the CORS middleware."""
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


# --- Phase 3: database status in the health payload -------------------------


def test_health_reports_database_not_configured(unconfigured_db: None) -> None:
    """No URI set: honest about being unconfigured, but still 'ok'."""
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["database"] == {
        "configured": False,
        "connected": False,
        "type": "mongodb",
    }


def test_health_reports_database_connected(connected_db: FakeMongoClient) -> None:
    """Test 4: configured and reachable."""
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["database"] == {
        "configured": True,
        "connected": True,
        "type": "mongodb",
    }


def test_health_reports_degraded_when_database_unreachable(
    failing_db: FakeMongoClient,
) -> None:
    """Configured but unreachable is 'degraded' — still HTTP 200."""
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "degraded"
    assert body["data"]["database"] == {
        "configured": True,
        "connected": False,
        "type": "mongodb",
    }


def test_health_pings_live_rather_than_caching_startup_state(
    connected_db: FakeMongoClient,
) -> None:
    """Each health call re-checks the database instead of trusting startup."""
    client.get("/api/health")
    client.get("/api/health")

    assert connected_db.admin.ping_count == 2


def test_lifespan_startup_and_shutdown_run_cleanly(unconfigured_db: None) -> None:
    """Using TestClient as a context manager triggers the lifespan hooks.

    With no URI configured this must still start and stop without raising.
    """
    with TestClient(app) as lifespan_client:
        assert lifespan_client.get("/api/health").status_code == 200


# --- Phase 12: AI provider readiness ----------------------------------------


def test_health_reports_ai_configured(
    unconfigured_db: None, groq_configured: None
) -> None:
    data = client.get("/api/health").json()["data"]

    assert data["ai"]["configured"] is True
    assert data["ai"]["provider"] == "groq"
    assert data["ai"]["model"]


def test_health_reports_ai_not_configured(
    unconfigured_db: None, groq_unconfigured: None
) -> None:
    """Honest about a missing key rather than silently claiming readiness."""
    data = client.get("/api/health").json()["data"]

    assert data["ai"]["configured"] is False


def test_health_never_exposes_the_api_key(
    unconfigured_db: None, groq_configured: None
) -> None:
    from app.config import settings

    raw = client.get("/api/health").text

    assert settings.GROQ_API_KEY not in raw
    assert "gsk_" not in raw
    assert "api_key" not in raw.lower()


def test_health_does_not_call_the_provider(
    unconfigured_db: None, groq_configured: None, recorded_generate
) -> None:
    """A health check must not spend provider budget or wait on a third party."""
    client.get("/api/health")

    assert recorded_generate.calls == []


def test_database_status_is_still_accurate_alongside_ai(
    connected_db: FakeMongoClient,
) -> None:
    data = client.get("/api/health").json()["data"]

    assert data["database"]["connected"] is True
    assert "ai" in data
