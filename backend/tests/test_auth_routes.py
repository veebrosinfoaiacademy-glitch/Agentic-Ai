"""Phase 8 tests: the /api/auth HTTP contract, plus security invariants."""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FakeUsersCollection

client = TestClient(app)

REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"
ME = "/api/auth/me"

EMAIL = "user@example.com"
PASSWORD = "unit-test-passphrase-7fQz"


# --- Registration -----------------------------------------------------------


def test_register_returns_the_standard_envelope(users: FakeUsersCollection) -> None:
    response = client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"success", "message", "data"}
    assert body["success"] is True
    assert body["message"] == "User registered successfully"
    assert set(body["data"].keys()) == {"id", "email", "created_at"}
    assert body["data"]["email"] == EMAIL


def test_register_response_never_contains_credentials(
    users: FakeUsersCollection,
) -> None:
    raw = client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD}).text

    assert PASSWORD not in raw
    assert "password" not in raw.lower()
    assert "$argon2id$" not in raw


@pytest.mark.parametrize(
    ("submitted", "stored"),
    [
        ("User@Example.COM", "user@example.com"),
        ("  spaced@example.com  ", "spaced@example.com"),
        ("MiXeD@CaSe.Org", "mixed@case.org"),
    ],
)
def test_email_is_normalised(
    users: FakeUsersCollection, submitted: str, stored: str
) -> None:
    response = client.post(REGISTER, json={"email": submitted, "password": PASSWORD})

    assert response.status_code == 201
    assert response.json()["data"]["email"] == stored
    assert users.documents[0]["email"] == stored


def test_normalised_email_blocks_a_case_variant_duplicate(
    users: FakeUsersCollection,
) -> None:
    """Without normalisation these would be two separate accounts."""
    client.post(REGISTER, json={"email": "User@Example.com", "password": PASSWORD})

    response = client.post(
        REGISTER, json={"email": "user@EXAMPLE.com", "password": PASSWORD}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_ALREADY_EXISTS"


def test_duplicate_registration_is_rejected(users: FakeUsersCollection) -> None:
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    response = client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "USER_ALREADY_EXISTS"


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "@example.com", "user@", "user @example.com", "", None],
    ids=["no-at", "no-local", "no-domain", "space", "empty", "null"],
)
def test_invalid_emails_are_rejected(users: FakeUsersCollection, email) -> None:
    response = client.post(REGISTER, json={"email": email, "password": PASSWORD})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "password",
    ["", "short", "1234567", "       ", "\t\n  \t", None],
    ids=["empty", "short", "seven", "spaces", "whitespace", "null"],
)
def test_weak_passwords_are_rejected(users: FakeUsersCollection, password) -> None:
    response = client.post(REGISTER, json={"email": EMAIL, "password": password})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert users.documents == []


def test_eight_character_password_is_accepted(users: FakeUsersCollection) -> None:
    response = client.post(REGISTER, json={"email": EMAIL, "password": "12345678"})

    assert response.status_code == 201


def test_very_long_password_is_rejected(users: FakeUsersCollection) -> None:
    """An unbounded password would let one request burn CPU in the hasher."""
    response = client.post(REGISTER, json={"email": EMAIL, "password": "x" * 500})

    assert response.status_code == 422


def test_registration_reports_a_database_outage(
    failing_users: FakeUsersCollection,
) -> None:
    response = client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


# --- Login ------------------------------------------------------------------


def test_login_returns_a_token(users: FakeUsersCollection, jwt_secret: str) -> None:
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    response = client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Login successful"
    assert set(body["data"].keys()) == {"access_token", "token_type", "expires_in"}
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["expires_in"] > 0
    assert body["data"]["access_token"].count(".") == 2


def test_login_accepts_a_differently_cased_email(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    response = client.post(
        LOGIN, json={"email": "  USER@Example.COM ", "password": PASSWORD}
    )

    assert response.status_code == 200


def test_wrong_password_is_rejected(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    response = client.post(LOGIN, json={"email": EMAIL, "password": "wrong-passphrase-7fQz"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_unknown_email_and_wrong_password_are_byte_identical(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    """The whole anti-enumeration defence, verified at the HTTP boundary."""
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    wrong_password = client.post(
        LOGIN, json={"email": EMAIL, "password": "wrong-passphrase-7fQz"}
    )
    unknown_email = client.post(
        LOGIN, json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code
    assert wrong_password.json() == unknown_email.json()
    assert unknown_email.json()["message"] == "Invalid email or password"


def test_login_response_never_contains_a_hash(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})

    raw = client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD}).text

    assert "$argon2id$" not in raw
    assert "password_hash" not in raw
    assert PASSWORD not in raw


@pytest.mark.parametrize(
    "payload",
    [{}, {"email": EMAIL}, {"password": PASSWORD}, {"email": "bad", "password": "x"}],
    ids=["empty", "no-password", "no-email", "invalid-email"],
)
def test_malformed_login_requests_are_rejected(
    users: FakeUsersCollection, payload: dict
) -> None:
    response = client.post(LOGIN, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_reports_a_database_outage(
    failing_users: FakeUsersCollection, jwt_secret: str
) -> None:
    response = client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


# --- Full round trip --------------------------------------------------------


def test_register_login_then_me(users: FakeUsersCollection, jwt_secret: str) -> None:
    registered = client.post(
        REGISTER, json={"email": EMAIL, "password": PASSWORD}
    ).json()["data"]

    token = client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD}).json()[
        "data"
    ]["access_token"]

    me = client.get(ME, headers={"Authorization": f"Bearer {token}"}).json()["data"]

    assert me["id"] == registered["id"]
    assert me["email"] == registered["email"]


# --- Swagger ----------------------------------------------------------------


def test_auth_endpoints_appear_in_openapi() -> None:
    spec = client.get("/openapi.json").json()

    for path in (REGISTER, LOGIN):
        assert path in spec["paths"]
        assert spec["paths"][path]["post"]["summary"]
    assert ME in spec["paths"]
    assert spec["paths"][ME]["get"]["summary"]


def test_bearer_security_scheme_is_advertised() -> None:
    """So Swagger shows an Authorize button and can call /me."""
    spec = client.get("/openapi.json").json()

    schemes = spec["components"]["securitySchemes"]
    assert "Bearer" in schemes
    assert schemes["Bearer"]["type"] == "http"
    assert schemes["Bearer"]["scheme"] == "bearer"

    # Only /me is protected in this phase.
    assert "security" in spec["paths"][ME]["get"]
    assert "security" not in spec["paths"][LOGIN]["post"]


def test_openapi_never_exposes_the_signing_secret(jwt_secret: str) -> None:
    assert jwt_secret not in client.get("/openapi.json").text


# --- Which endpoints stay public (Phase 10 changed this) --------------------


def test_public_endpoints_still_work_without_a_token() -> None:
    """Health, register, login and supported-types remain anonymous.

    Phase 8 asserted the agent routes were open too. Phase 10 deliberately
    closed them, so that half of the assertion moved to
    test_route_protection.py rather than being deleted.
    """
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/documents/supported-types").status_code == 200

    # Registration and login must stay reachable, or nobody could ever sign in.
    schema = client.get("/openapi.json").json()
    assert "security" not in schema["paths"][REGISTER]["post"]
    assert "security" not in schema["paths"][LOGIN]["post"]


def test_agent_and_upload_endpoints_now_require_a_token(
    recorded_generate,
) -> None:
    """The Phase 10 contract change, asserted at the HTTP boundary."""
    anonymous = [
        ("post", "/api/content/summarize", {"text": "x", "summary_type": "short"}),
        ("post", "/api/developer/explain", {"language": "python", "code": "x = 1"}),
        ("post", "/api/ai/test", {"prompt": "hello"}),
    ]
    for method, path, payload in anonymous:
        response = getattr(client, method)(path, json=payload)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "TOKEN_MISSING"

    upload = client.post(
        "/api/documents/upload",
        files={"file": ("a.txt", b"hello there", "text/plain")},
    )
    assert upload.status_code == 401


# --- SECURITY ---------------------------------------------------------------


def test_auth_source_has_no_execution_primitives() -> None:
    """AST-based, following Phase 6 — a docstring mentioning exec must not trip."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    targets = [
        app_dir / "utils" / "security.py",
        app_dir / "services" / "auth_service.py",
        app_dir / "dependencies" / "auth.py",
        app_dir / "routes" / "auth.py",
        app_dir / "schemas" / "auth_schemas.py",
    ]

    forbidden_calls = {"exec", "eval", "compile", "__import__"}
    forbidden_attribute_calls = {
        ("os", "system"), ("os", "popen"), ("os", "execv"), ("pty", "spawn"),
    }
    forbidden_imports = {"subprocess", "pty", "importlib", "runpy"}

    offenders: list[str] = []

    for source_file in targets:
        assert source_file.exists(), f"missing: {source_file}"
        tree = ast.parse(source_file.read_text(encoding="utf-8"), str(source_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in forbidden_calls:
                    offenders.append(f"{source_file.name}:{node.lineno} {func.id}()")
                elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if (func.value.id, func.attr) in forbidden_attribute_calls:
                        offenders.append(
                            f"{source_file.name}:{node.lineno} "
                            f"{func.value.id}.{func.attr}()"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_imports:
                        offenders.append(f"{source_file.name}:{node.lineno} import")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in forbidden_imports:
                    offenders.append(f"{source_file.name}:{node.lineno} from-import")

    assert offenders == [], f"execution primitives found: {offenders}"


def test_password_hashing_happens_only_in_the_security_module() -> None:
    """Routes and services must not import a hashing library directly."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    hashing_modules = {"pwdlib", "bcrypt", "argon2", "hashlib", "passlib", "jwt"}

    offenders: list[str] = []
    allowed = {"security.py"}

    for source_file in app_dir.rglob("*.py"):
        if source_file.name in allowed:
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"), str(source_file))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in hashing_modules:
                    offenders.append(f"{source_file.name}:{node.lineno} {name}")

    assert offenders == [], f"crypto imported outside security.py: {offenders}"


def test_no_response_or_schema_exposes_secrets(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    from app.config import settings

    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})
    token = client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD}).json()[
        "data"
    ]["access_token"]

    bodies = [
        client.post(REGISTER, json={"email": "b@example.com", "password": PASSWORD}).text,
        client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD}).text,
        client.get(ME, headers={"Authorization": f"Bearer {token}"}).text,
        client.get("/api/health").text,
        client.get("/openapi.json").text,
    ]

    for body in bodies:
        assert jwt_secret not in body
        assert PASSWORD not in body
        assert "$argon2id$" not in body
        assert "password_hash" not in body
        assert "mongodb+srv" not in body
        if settings.GROQ_API_KEY:
            assert settings.GROQ_API_KEY not in body


def test_no_token_is_persisted_to_the_database(
    users: FakeUsersCollection, jwt_secret: str
) -> None:
    """Stateless tokens: nothing about them belongs in MongoDB."""
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})
    client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD})

    stored = str(users.documents)
    assert "access_token" not in stored
    assert "eyJ" not in stored  # a JWT always starts with this base64 prefix
    assert set(users.documents[0].keys()) == {
        "_id", "email", "password_hash", "created_at", "updated_at",
    }


def test_authorization_header_is_never_logged(
    users: FakeUsersCollection, jwt_secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD})
    token = client.post(LOGIN, json={"email": EMAIL, "password": PASSWORD}).json()[
        "data"
    ]["access_token"]

    with caplog.at_level("DEBUG"):
        client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert token not in caplog.text
    assert "Authorization" not in caplog.text
    assert PASSWORD not in caplog.text
