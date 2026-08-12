"""Phase 14 tests: document persistence, ownership and CRUD.

Entirely offline — in-memory collections, no Atlas.
"""

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.document_schemas import MAX_PAGE_SIZE, MAX_TITLE_CHARS
from app.services.document_service import document_repository
from app.utils.errors import AppError
from tests.conftest import FakeCollection, FakeUsersCollection, make_docx, make_pdf

client = TestClient(app)

BASE = "/api/documents"
UPLOAD = f"{BASE}/upload"


def sign_up(email: str) -> str:
    from app.services.auth_service import auth_service

    auth_service.register(email, "document-tests-passphrase")
    return auth_service.authenticate(email, "document-tests-passphrase").access_token


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def upload(token: str, name: str = "notes.txt", data: bytes = b"Some document text.",
           ctype: str = "text/plain") -> dict:
    response = client.post(
        UPLOAD, files={"file": (name, data, ctype)}, headers=auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --- Persistence ------------------------------------------------------------


def test_upload_stores_the_extracted_text(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("storer@example.com")

    data = upload(token)

    assert data["id"]
    assert data["text"] == "Some document text."
    assert data["characters"] == len("Some document text.")
    stored = documents.documents[0]
    assert stored["text"] == "Some document text."
    assert stored["filename"] == "notes.txt"
    assert stored["title"] == "notes.txt"  # title starts as the filename


def test_the_stored_document_is_owned_by_the_uploader(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("owner@example.com")

    upload(token)

    assert isinstance(documents.documents[0]["user_id"], ObjectId)


def test_the_original_binary_is_never_stored(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    """Only extracted text is kept — the file itself is discarded."""
    token = sign_up("nobinary@example.com")

    client.post(
        UPLOAD,
        files={"file": ("doc.pdf", make_pdf(["Page one."]), "application/pdf")},
        headers=auth(token),
    )

    stored = documents.documents[0]
    assert not any(isinstance(value, bytes) for value in stored.values())
    assert set(stored) == {
        "_id", "user_id", "filename", "title", "extension", "content_type",
        "size_bytes", "characters", "text", "metadata", "created_at", "updated_at",
    }


@pytest.mark.parametrize(
    ("name", "data", "ctype", "expected"),
    [
        ("a.txt", b"plain text", "text/plain", {"encoding": "utf-8"}),
        ("a.md", b"# Title\n\ntext", "text/markdown", {"heading_count": 1}),
        ("a.csv", b"x,y\n1,2", "text/csv", {"rows": 1, "columns": 2}),
    ],
    ids=["txt", "markdown", "csv"],
)
def test_format_metadata_survives_persistence(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection,
    name: str, data: bytes, ctype: str, expected: dict,
) -> None:
    # Derive a valid local-part from the extension, not a raw filename slice.
    token = sign_up(f"meta-{name.rsplit('.', 1)[-1]}@example.com")

    result = upload(token, name, data, ctype)

    for key, value in expected.items():
        assert result["metadata"][key] == value
    assert documents.documents[0]["metadata"][key] == value


def test_pdf_and_docx_metadata_survive_persistence(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("binmeta@example.com")

    pdf = upload(token, "a.pdf", make_pdf(["One.", "Two."]), "application/pdf")
    docx = upload(
        token, "a.docx",
        make_docx(paragraphs=["Intro."], tables=[[["A", "B"]]]),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert pdf["metadata"]["page_count"] == 2
    assert docx["metadata"]["table_count"] == 1


def test_a_traversal_filename_is_stored_sanitised(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("traversal@example.com")

    data = upload(token, "../../etc/passwd.txt")

    assert data["filename"] == "passwd.txt"
    assert "/" not in documents.documents[0]["filename"]


def test_existing_validation_still_rejects_bad_uploads(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    """Phase 7's guards are reused untouched — nothing is stored on failure."""
    token = sign_up("rejects@example.com")

    cases = [
        (("script.py", b"print(1)", "text/x-python"), 415),        # extension
        (("fake.pdf", b"not a pdf at all", "application/pdf"), 422),  # signature
        (("notes.txt", b"", "text/plain"), 422),                   # empty
        (("blank.txt", b"   \n\n ", "text/plain"), 422),           # no text
        (("notes.txt", b"x", "application/pdf"), 415),             # MIME mismatch
    ]
    for (name, data, ctype), expected in cases:
        response = client.post(
            UPLOAD, files={"file": (name, data, ctype)}, headers=auth(token)
        )
        assert response.status_code == expected, name

    assert documents.documents == []


def test_persistence_failure_is_reported_cleanly(
    users: FakeUsersCollection, jwt_secret: str, failing_documents: FakeCollection
) -> None:
    """Never claim a document was stored when the write failed."""
    token = sign_up("failstore@example.com")

    response = client.post(
        UPLOAD, files={"file": ("a.txt", b"text", "text/plain")}, headers=auth(token)
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DATABASE_UNAVAILABLE"
    for leak in ("pymongo", "ServerSelection", "mongodb", "Traceback"):
        assert leak.lower() not in response.text.lower()


# --- Listing ----------------------------------------------------------------


def test_list_returns_only_the_callers_documents(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token_a = sign_up("lista@example.com")
    token_b = sign_up("listb@example.com")
    upload(token_a, "a-one.txt")
    upload(token_a, "a-two.txt")
    upload(token_b, "b-one.txt")

    body_a = client.get(BASE, headers=auth(token_a)).json()["data"]
    body_b = client.get(BASE, headers=auth(token_b)).json()["data"]

    assert body_a["total"] == 2
    assert {d["filename"] for d in body_a["documents"]} == {"a-one.txt", "a-two.txt"}
    assert [d["filename"] for d in body_b["documents"]] == ["b-one.txt"]


def test_list_omits_the_extracted_text(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    """A page of twenty documents should not carry megabytes of content."""
    token = sign_up("listtext@example.com")
    upload(token, "a.txt", b"a very long document body" * 100)

    body = client.get(BASE, headers=auth(token)).json()["data"]

    assert "text" not in body["documents"][0]
    assert body["documents"][0]["characters"] > 0


def test_list_query_always_filters_by_owner(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("listquery@example.com")
    upload(token)
    documents.queries.clear()

    client.get(BASE, headers=auth(token))

    assert documents.queries
    for query in documents.queries:
        assert "user_id" in query


def test_list_paginates(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("paginate@example.com")
    for index in range(5):
        upload(token, f"doc{index}.txt")

    first = client.get(BASE, params={"page": 1, "page_size": 2}, headers=auth(token))
    last = client.get(BASE, params={"page": 3, "page_size": 2}, headers=auth(token))

    assert first.json()["data"]["total"] == 5
    assert len(first.json()["data"]["documents"]) == 2
    assert first.json()["data"]["has_more"] is True
    assert last.json()["data"]["has_more"] is False


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": MAX_PAGE_SIZE + 1}],
    ids=["page-zero", "page-negative", "size-zero", "size-too-large"],
)
def test_invalid_pagination_is_rejected(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection, params: dict
) -> None:
    token = sign_up(f"page{abs(hash(str(params))) % 9999}@example.com")

    response = client.get(BASE, params=params, headers=auth(token))

    assert response.status_code == 422


def test_list_is_empty_for_a_new_user(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("emptylist@example.com")

    body = client.get(BASE, headers=auth(token)).json()["data"]

    assert body["documents"] == []
    assert body["total"] == 0


# --- Detail, rename, delete -------------------------------------------------


def test_detail_returns_the_full_text(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("detail@example.com")
    created = upload(token)

    body = client.get(f"{BASE}/{created['id']}", headers=auth(token)).json()["data"]

    assert body["text"] == "Some document text."
    assert body["id"] == created["id"]
    assert "user_id" not in body


def test_rename_changes_only_the_title(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("rename@example.com")
    created = upload(token)
    before = dict(documents.documents[0])

    response = client.patch(
        f"{BASE}/{created['id']}", json={"title": "Annual report"}, headers=auth(token)
    )

    assert response.status_code == 200
    assert response.json()["data"]["title"] == "Annual report"
    after = documents.documents[0]
    assert after["filename"] == before["filename"]  # the original name is immutable
    assert after["text"] == before["text"]
    assert after["user_id"] == before["user_id"]
    assert after["created_at"] == before["created_at"]


def test_rename_cannot_change_protected_fields(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("protected@example.com")
    created = upload(token)
    before = dict(documents.documents[0])

    client.patch(
        f"{BASE}/{created['id']}",
        json={
            "title": "New title",
            "filename": "hijacked.txt",
            "text": "replaced content",
            "user_id": str(ObjectId()),
        },
        headers=auth(token),
    )

    after = documents.documents[0]
    assert after["title"] == "New title"
    assert after["filename"] == before["filename"]
    assert after["text"] == before["text"]
    assert after["user_id"] == before["user_id"]


@pytest.mark.parametrize(
    "title", ["", "   ", "x" * (MAX_TITLE_CHARS + 1), None],
    ids=["empty", "spaces", "too-long", "null"],
)
def test_invalid_titles_are_rejected(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection, title
) -> None:
    token = sign_up(f"title{abs(hash(str(title))) % 9999}@example.com")
    created = upload(token)

    response = client.patch(
        f"{BASE}/{created['id']}", json={"title": title}, headers=auth(token)
    )

    assert response.status_code == 422


def test_delete_removes_the_document(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("delete@example.com")
    created = upload(token)

    response = client.delete(f"{BASE}/{created['id']}", headers=auth(token))

    assert response.status_code == 200
    assert documents.documents == []
    assert client.get(f"{BASE}/{created['id']}", headers=auth(token)).status_code == 404


def test_delete_leaves_other_documents_intact(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("deleteone@example.com")
    keep = upload(token, "keep.txt")
    remove = upload(token, "remove.txt")

    client.delete(f"{BASE}/{remove['id']}", headers=auth(token))

    assert len(documents.documents) == 1
    assert client.get(f"{BASE}/{keep['id']}", headers=auth(token)).status_code == 200


# --- Ownership: the core security requirement -------------------------------


@pytest.mark.parametrize(
    ("method", "payload"),
    [("get", None), ("patch", {"title": "hijacked"}), ("delete", None)],
    ids=["read", "rename", "delete"],
)
def test_user_b_cannot_touch_user_a_document(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection,
    method: str, payload,
) -> None:
    token_a = sign_up("victim@example.com")
    token_b = sign_up("attacker@example.com")
    created = upload(token_a, "private.txt", b"User A private content.")

    response = getattr(client, method)(
        f"{BASE}/{created['id']}",
        headers=auth(token_b),
        **({"json": payload} if payload else {}),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert "User A private content." not in response.text
    # Nothing changed and nothing was removed.
    assert documents.documents[0]["title"] == "private.txt"


def test_a_foreign_document_looks_exactly_like_a_missing_one(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    """Otherwise the endpoint becomes an oracle for which ids exist."""
    token_a = sign_up("owner2@example.com")
    token_b = sign_up("attacker2@example.com")
    owned_by_a = upload(token_a)["id"]

    foreign = client.get(f"{BASE}/{owned_by_a}", headers=auth(token_b))
    missing = client.get(f"{BASE}/{ObjectId()}", headers=auth(token_b))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize("operation", ["get", "rename", "delete"])
def test_every_operation_scopes_its_query_by_owner(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection,
    operation: str,
) -> None:
    token = sign_up(f"scoped{len(operation)}@example.com")
    created = upload(token)
    documents.queries.clear()

    actions = {
        "get": lambda: client.get(f"{BASE}/{created['id']}", headers=auth(token)),
        "rename": lambda: client.patch(
            f"{BASE}/{created['id']}", json={"title": "x"}, headers=auth(token)
        ),
        "delete": lambda: client.delete(f"{BASE}/{created['id']}", headers=auth(token)),
    }
    actions[operation]()

    assert documents.queries
    for query in documents.queries:
        assert "user_id" in query, f"{operation} issued an unscoped query: {query}"


# --- Invalid ids ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id", ["not-an-objectid", "12345", "z" * 24],
    ids=["prose", "short", "non-hex"],
)
def test_malformed_document_id_is_a_clean_error(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection, bad_id: str
) -> None:
    token = sign_up(f"badid{len(bad_id)}@example.com")

    response = client.get(f"{BASE}/{bad_id}", headers=auth(token))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ID"
    for leak in ("Traceback", "bson", "pymongo", "ObjectId"):
        assert leak not in response.text


@pytest.mark.parametrize("bad_id", [None, "", "   "], ids=["none", "empty", "spaces"])
def test_unusable_ids_are_rejected_at_the_service(
    documents: FakeCollection, bad_id
) -> None:
    """ObjectId(None) silently generates a new id, so the type check is first."""
    with pytest.raises(AppError) as exc_info:
        document_repository.get_owned(str(ObjectId()), bad_id)

    assert exc_info.value.code == "INVALID_ID"


# --- Authentication ---------------------------------------------------------


def test_every_document_route_requires_a_token() -> None:
    document_id = str(ObjectId())
    anonymous = [
        ("get", BASE, None),
        ("get", f"{BASE}/{document_id}", None),
        ("patch", f"{BASE}/{document_id}", {"title": "x"}),
        ("delete", f"{BASE}/{document_id}", None),
    ]

    for method, path, payload in anonymous:
        response = getattr(client, method)(path, **({"json": payload} if payload else {}))
        assert response.status_code == 401, f"{method.upper()} {path}"
        assert response.json()["error"]["code"] == "TOKEN_MISSING"


def test_anonymous_upload_never_stores_anything(documents: FakeCollection) -> None:
    response = client.post(UPLOAD, files={"file": ("a.txt", b"x", "text/plain")})

    assert response.status_code == 401
    assert documents.documents == []


def test_supported_types_stays_public() -> None:
    """Global configuration, no user data — unchanged from Phase 7."""
    assert client.get(f"{BASE}/supported-types").status_code == 200


# --- Documented and safe ----------------------------------------------------


def test_all_document_routes_are_documented_and_protected() -> None:
    spec = client.get("/openapi.json").json()

    protected = [
        ("post", UPLOAD), ("get", BASE),
        ("get", f"{BASE}/{{document_id}}"),
        ("patch", f"{BASE}/{{document_id}}"),
        ("delete", f"{BASE}/{{document_id}}"),
    ]
    for method, path in protected:
        operation = spec["paths"][path][method]
        assert operation["summary"], f"{method} {path}"
        assert "security" in operation, f"{method} {path} is not protected"

    assert "security" not in spec["paths"][f"{BASE}/supported-types"]["get"]


def test_document_request_schemas_expose_no_identity_fields() -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    forbidden = {"user_id", "userId", "owner_id", "account_id"}
    offenders = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        if "Document" in name
        for field in schema.get("properties", {})
        if field in forbidden
    ]

    assert offenders == []


def test_responses_never_expose_the_owner_id(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection
) -> None:
    token = sign_up("noowner@example.com")
    created = upload(token)

    for response in (
        client.get(BASE, headers=auth(token)),
        client.get(f"{BASE}/{created['id']}", headers=auth(token)),
    ):
        assert "user_id" not in response.text


def test_document_text_is_never_logged(
    users: FakeUsersCollection, jwt_secret: str, documents: FakeCollection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Uploaded content may be confidential; only sizes and ids are logged."""
    secret_text = "PATIENT RECORD: confidential clinical notes"
    token = sign_up("nolog@example.com")

    with caplog.at_level("DEBUG"):
        created = upload(token, "record.txt", secret_text.encode())
        client.get(f"{BASE}/{created['id']}", headers=auth(token))

    assert secret_text not in caplog.text
    assert "confidential" not in caplog.text
