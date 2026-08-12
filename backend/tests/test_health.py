"""Phase 2 tests: application boots, health endpoint works, errors are shaped.

TestClient runs the real FastAPI app in-process — no server needs to be
running, and no network calls are made.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_app_imports_and_has_metadata() -> None:
    """Test 3: the application object can be imported without errors."""
    assert app.title
    assert app.version


def test_health_returns_ok() -> None:
    """Test 1: GET /api/health returns 200 with success=True and status ok."""
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


def test_health_response_structure() -> None:
    """Test 2: the response matches the common success envelope."""
    body = client.get("/api/health").json()

    assert set(body.keys()) == {"success", "message", "data"}
    assert set(body["data"].keys()) == {"status", "service", "version"}
    assert isinstance(body["message"], str)


def test_health_does_not_leak_secrets() -> None:
    """The health payload must never echo configuration secrets."""
    raw = client.get("/api/health").text.lower()

    for secret_name in ("groq_api_key", "mongodb_uri", "jwt_secret", "password"):
        assert secret_name not in raw


def test_unknown_route_uses_error_envelope() -> None:
    """A 404 flows through our handler, not Starlette's default shape."""
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_openapi_schema_is_available() -> None:
    """Swagger's underlying schema is served and includes the health route."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_cors_headers_present_for_allowed_origin() -> None:
    """The React dev origin is echoed back by the CORS middleware."""
    response = client.get(
        "/api/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
