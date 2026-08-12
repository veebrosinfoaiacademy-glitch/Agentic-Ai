"""Phase 7 tests: the /api/documents HTTP contract, plus security invariants.

The security section is the important part: uploads are hostile input, and
these tests pin the properties that keep them harmless.
"""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.conftest import make_docx, make_pdf, make_pdf_without_text

client = TestClient(app)

# Phase 10 protects these routes. These tests cover behaviour, not
# authentication, so they run as a signed-in user. Protection itself is
# verified in test_route_protection.py against the real dependency.
# Phase 14 persists uploads, so these behaviour tests also need a documents
# collection. Persistence itself is covered in test_document_persistence.py.
pytestmark = pytest.mark.usefixtures("authenticated", "documents")

UPLOAD = "/api/documents/upload"

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def upload(filename: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post(UPLOAD, files={"file": (filename, data, content_type)})


# --- Success path -----------------------------------------------------------


def test_txt_upload_returns_the_standard_envelope() -> None:
    response = upload("notes.txt", b"Hello document world.", "text/plain")

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"success", "message", "data"}
    assert body["success"] is True
    assert body["message"] == "Document processed successfully"

    data = body["data"]
    assert data["filename"] == "notes.txt"
    assert data["extension"] == ".txt"
    assert data["size_bytes"] == 21
    assert data["characters"] == 21
    assert data["text"] == "Hello document world."
    assert data["metadata"]["encoding"] == "utf-8"


def test_markdown_upload_preserves_syntax() -> None:
    response = upload("readme.md", b"# Title\n\n- item one\n- item two", "text/markdown")

    assert response.status_code == 201
    text = response.json()["data"]["text"]
    assert "# Title" in text
    assert "- item one" in text


def test_csv_upload_returns_readable_text_and_metadata() -> None:
    response = upload(
        "people.csv", b"name,age,city\nAlice,22,Chennai\nBob,25,Bangalore", "text/csv"
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert "Header: name, age, city" in data["text"]
    assert "Alice | 22 | Chennai" in data["text"]
    assert data["metadata"]["rows"] == 2
    assert data["metadata"]["columns"] == 3


def test_pdf_upload_returns_page_metadata() -> None:
    response = upload(
        "report.pdf", make_pdf(["Page one text.", "Page two text."]), "application/pdf"
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["metadata"]["page_count"] == 2
    assert "--- Page 1 ---" in data["text"]
    assert "Page two text." in data["text"]


def test_docx_upload_returns_paragraph_and_table_metadata() -> None:
    response = upload(
        "doc.docx",
        make_docx(paragraphs=["Some intro text."], tables=[[["Name", "Role"]]]),
        DOCX_MIME,
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert "Some intro text." in data["text"]
    assert "Name | Role" in data["text"]
    assert data["metadata"]["table_count"] == 1


# --- Validation errors ------------------------------------------------------


@pytest.mark.parametrize(
    "filename", ["script.py", "archive.zip", "photo.png", "data.json", "noext"]
)
def test_unsupported_extensions_are_rejected(filename: str) -> None:
    response = upload(filename, b"some content")

    assert response.status_code == 415
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "DOCUMENT_TYPE_NOT_SUPPORTED"


def test_contradictory_mime_type_is_rejected() -> None:
    response = upload("notes.txt", b"text", "application/pdf")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "DOCUMENT_TYPE_NOT_SUPPORTED"


def test_oversized_upload_is_rejected() -> None:
    response = upload("big.txt", b"x" * (settings.max_upload_bytes + 1), "text/plain")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "DOCUMENT_TOO_LARGE"


def test_extracted_text_over_the_limit_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_MAX_EXTRACTED_CHARACTERS", 50)

    response = upload("long.txt", b"y" * 500, "text/plain")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "DOCUMENT_CONTENT_TOO_LARGE"


def test_empty_file_is_rejected() -> None:
    response = upload("empty.txt", b"", "text/plain")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DOCUMENT_INVALID"


def test_document_with_no_text_is_reported() -> None:
    response = upload("blank.txt", b"   \n\n  ", "text/plain")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DOCUMENT_TEXT_NOT_FOUND"


def test_image_only_pdf_is_reported_without_claiming_ocr() -> None:
    response = upload("scan.pdf", make_pdf_without_text(), "application/pdf")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "DOCUMENT_TEXT_NOT_FOUND"
    assert "OCR" in body["message"]


def test_corrupt_pdf_is_rejected() -> None:
    response = upload("broken.pdf", b"%PDF-1.4\nbut then garbage", "application/pdf")

    assert response.status_code == 422
    assert response.json()["error"]["code"] in {
        "DOCUMENT_INVALID",
        "DOCUMENT_EXTRACTION_FAILED",
    }


def test_missing_file_is_rejected() -> None:
    response = client.post(UPLOAD)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_malformed_multipart_body_is_rejected() -> None:
    response = client.post(
        UPLOAD,
        content=b"not a real multipart body",
        headers={"Content-Type": "multipart/form-data; boundary=xyz"},
    )

    assert response.status_code in {400, 422}
    assert response.json()["success"] is False


def test_wrong_form_field_name_is_rejected() -> None:
    response = client.post(UPLOAD, files={"document": ("a.txt", b"x", "text/plain")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Supported types endpoint -----------------------------------------------


def test_supported_types_reports_limits_from_configuration() -> None:
    """A GET, so still 200 — only uploads became 201 Created."""
    response = client.get("/api/documents/supported-types")

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data["extensions"]) == {".txt", ".md", ".csv", ".pdf", ".docx"}
    assert data["max_file_size_mb"] == settings.MAX_UPLOAD_MB
    assert data["max_extracted_characters"] == settings.DOCUMENT_MAX_EXTRACTED_CHARACTERS
    assert data["ocr_supported"] is False


def test_document_endpoints_appear_in_openapi() -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert UPLOAD in paths
    assert "/api/documents/supported-types" in paths

    spec = paths[UPLOAD]["post"]
    assert spec["summary"]
    # Accepted formats and the no-OCR behaviour are documented for clients.
    assert ".pdf" in spec["description"]
    assert "OCR" in spec["description"]
    assert "413" in spec["responses"]
    assert "415" in spec["responses"]


# --- SECURITY ---------------------------------------------------------------


def test_response_never_exposes_a_filesystem_path() -> None:
    """Not even the client's own path — it is reduced to a basename."""
    response = upload("../../../etc/secret/notes.txt", b"content", "text/plain")

    assert response.status_code == 201
    raw = response.text
    assert response.json()["data"]["filename"] == "notes.txt"
    for leak in ("/etc/", "/var/", "/tmp/", "/Users/", "..", "site-packages"):
        assert leak not in raw


def test_a_python_file_renamed_to_txt_is_treated_as_inert_text() -> None:
    """Content that would be destructive if run is merely read as characters."""
    payload = b"import os\nos.system('rm -rf /')\nprint('executed')\n"

    response = upload("innocent.txt", payload, "text/plain")

    assert response.status_code == 201
    # Returned verbatim as text. Nothing imported it, ran it, or evaluated it.
    assert "os.system" in response.json()["data"]["text"]


def test_csv_formula_injection_is_returned_as_text() -> None:
    response = upload("f.csv", b'formula\n"=SUM(1,2)"\n"=cmd|calc"', "text/csv")

    assert response.status_code == 201
    text = response.json()["data"]["text"]
    assert "=SUM(1,2)" in text


def test_uploads_are_not_written_to_disk(tmp_path: Path) -> None:
    """Processing is fully in memory, so there is no temp file to leak."""
    before = set(tmp_path.iterdir())

    upload("notes.txt", b"some content", "text/plain")
    upload("doc.pdf", make_pdf(["text"]), "application/pdf")

    assert set(tmp_path.iterdir()) == before


def test_no_temporary_files_survive_a_failed_upload(tmp_path: Path) -> None:
    """Cleanup must hold on the error path too."""
    before = set(tmp_path.iterdir())

    upload("broken.pdf", b"%PDF-1.4 corrupt", "application/pdf")
    upload("huge.txt", b"x" * (settings.max_upload_bytes + 1), "text/plain")

    assert set(tmp_path.iterdir()) == before


def test_document_processing_source_has_no_execution_primitives() -> None:
    """AST-based, so the word "subprocess" in a docstring does not trip it.

    Substring matching cannot tell `re.compile()` from bare `compile()`, nor a
    comment from code. Parsing can. A regression here would turn document
    upload into remote code execution.
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    targets = [
        app_dir / "utils" / "document_extractors.py",
        app_dir / "services" / "document_service.py",
        app_dir / "routes" / "documents.py",
        app_dir / "schemas" / "document_schemas.py",
        # Phase 14 added persistence and the conversation bridge; both handle
        # user-supplied content and must stay execution-free.
        app_dir / "services" / "conversation_service.py",
        app_dir / "schemas" / "conversation_schemas.py",
    ]

    forbidden_calls = {"exec", "eval", "compile", "__import__"}
    forbidden_attribute_calls = {
        ("os", "system"), ("os", "popen"), ("os", "execv"), ("os", "spawnv"),
        ("pty", "spawn"),
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
                        offenders.append(
                            f"{source_file.name}:{node.lineno} import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in forbidden_imports:
                    offenders.append(
                        f"{source_file.name}:{node.lineno} from {node.module}"
                    )

    assert offenders == [], f"execution primitives found: {offenders}"


def test_upload_persists_the_extracted_text(documents) -> None:
    """Phase 14 deliberately inverts Phase 7's "stores nothing" contract.

    The uploaded FILE is still never stored — only the extracted text and
    safe metadata, so the document can be reopened and reused.
    """
    response = upload("notes.txt", b"content", "text/plain")

    assert response.status_code == 201
    assert response.json()["data"]["id"]

    stored = documents.documents[0]
    assert stored["text"] == "content"
    assert "user_id" in stored
    # The binary itself is still never kept.
    assert not any(isinstance(v, bytes) for v in stored.values())


def test_upload_does_not_call_groq(recorded_generate) -> None:
    """Upload stays independent of AI processing in this phase."""
    response = upload("notes.txt", b"Some document content.", "text/plain")

    assert response.status_code == 201
    assert recorded_generate.calls == []
