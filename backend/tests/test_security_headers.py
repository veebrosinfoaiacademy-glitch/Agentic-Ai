"""Phase 15 tests: production security headers.

Small surface, but each header has to be present on the paths that matter and
absent where it would break something.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.utils.security_headers import API_CSP
from tests.conftest import FakeCollection, FakeUsersCollection

client = TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/health", None),
        ("get", "/api/documents/supported-types", None),
        ("get", "/api/usage", None),          # 401
        ("get", "/api/nope", None),           # 404
        ("post", "/api/auth/login", {"email": "x", "password": "y"}),  # 422
    ],
    ids=["health", "supported-types", "unauthorised", "not-found", "validation-error"],
)
def test_every_response_carries_the_base_headers(
    unconfigured_db: None, method: str, path: str, payload
) -> None:
    """Including error responses — that is where they are easiest to forget."""
    response = getattr(client, method)(path, **({"json": payload} if payload else {}))

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_api_responses_forbid_loading_anything(unconfigured_db: None) -> None:
    """A JSON API never legitimately loads a script, style or frame."""
    response = client.get("/api/health")

    assert response.headers["content-security-policy"] == API_CSP.decode()
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_error_responses_are_covered_too() -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert "content-security-policy" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_documentation_is_exempt_from_the_policy(path: str) -> None:
    """Swagger loads its bundle from a CDN and would blank under the API CSP.

    The trade-off is deliberate and documented: /docs is a development and
    operations tool, not a user-facing surface.
    """
    response = client.get(path)

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
    # The cheap headers still apply.
    assert response.headers["x-content-type-options"] == "nosniff"


def test_headers_do_not_disturb_the_response_body(unconfigured_db: None) -> None:
    body = client.get("/api/health").json()

    assert set(body.keys()) == {"success", "message", "data"}


def test_headers_coexist_with_the_request_id(unconfigured_db: None) -> None:
    response = client.get("/api/health")

    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_cors_headers_still_work_for_an_allowed_origin(unconfigured_db: None) -> None:
    """Security headers must not shadow the CORS middleware."""
    response = client.get(
        "/api/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_an_authenticated_json_response_is_covered(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    from app.services.auth_service import auth_service

    auth_service.register("headers@example.com", "header-tests-passphrase")
    token = auth_service.authenticate(
        "headers@example.com", "header-tests-passphrase"
    ).access_token

    response = client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == API_CSP.decode()
    assert response.headers["referrer-policy"] == "no-referrer"


def test_no_secret_is_ever_placed_in_a_header(
    users: FakeUsersCollection, jwt_secret: str, conversations: FakeCollection
) -> None:
    from app.config import settings

    response = client.get("/api/health")
    joined = " ".join(f"{k}: {v}" for k, v in response.headers.items())

    assert jwt_secret not in joined
    assert "mongodb+srv" not in joined
    if settings.GROQ_API_KEY:
        assert settings.GROQ_API_KEY not in joined
