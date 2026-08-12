"""Phase 7 tests: the document service pipeline.

Validation, size limits, type detection and the empty/oversized-text rules.
"""

import asyncio

import pytest

from app.config import settings
from app.schemas.document_schemas import DocumentType
from app.services.document_service import (
    _detect_type,
    _sanitize_filename,
    document_service,
)
from app.utils.errors import AppError
from tests.conftest import FakeUpload, make_docx, make_pdf, make_pdf_without_text


def process(filename: str | None, content_type: str | None, data: bytes):
    """Run the async service from a sync test.

    asyncio.run keeps the suite free of an async pytest plugin dependency.
    """
    return asyncio.run(
        document_service.process_upload(FakeUpload(filename, content_type, data))
    )


# --- Filename sanitisation --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("  report.pdf  ", "report.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("/absolute/path/notes.md", "notes.md"),
        ("C:\\Windows\\system32\\evil.csv", "evil.csv"),
        ("folder/sub/data.csv", "data.csv"),
    ],
    ids=["plain", "padded", "traversal", "absolute", "windows", "nested"],
)
def test_filenames_are_reduced_to_a_safe_basename(raw: str, expected: str) -> None:
    """A client-supplied filename is attacker-controlled input."""
    assert _sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    "raw", [None, "", "   ", ".", "..", "/", "\x00"],
    ids=["none", "empty", "spaces", "dot", "dotdot", "slash", "null"],
)
def test_unusable_filenames_are_rejected(raw: str | None) -> None:
    with pytest.raises(AppError) as exc_info:
        _sanitize_filename(raw)

    assert exc_info.value.code == "DOCUMENT_INVALID"


# --- Type detection ---------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("a.txt", "text/plain", DocumentType.TXT),
        ("a.md", "text/markdown", DocumentType.MARKDOWN),
        ("a.csv", "text/csv", DocumentType.CSV),
        ("a.pdf", "application/pdf", DocumentType.PDF),
        (
            "a.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            DocumentType.DOCX,
        ),
    ],
)
def test_matching_extension_and_mime_are_accepted(
    filename: str, content_type: str, expected: DocumentType
) -> None:
    assert _detect_type(filename, content_type) == expected


@pytest.mark.parametrize("extension", [".txt", ".md", ".csv", ".pdf", ".docx"])
def test_generic_mime_falls_back_to_the_extension(extension: str) -> None:
    """Browsers and curl often send octet-stream. That is not a mismatch."""
    assert _detect_type(f"file{extension}", "application/octet-stream").value == extension


@pytest.mark.parametrize("content_type", [None, "", "application/unknown-thing"])
def test_missing_or_unknown_mime_falls_back_to_the_extension(
    content_type: str | None,
) -> None:
    assert _detect_type("notes.txt", content_type) == DocumentType.TXT


def test_extension_is_case_insensitive() -> None:
    assert _detect_type("REPORT.PDF", "application/pdf") == DocumentType.PDF


def test_contradictory_mime_type_is_rejected() -> None:
    """A .txt claiming to be a PDF is a mismatch we can actually detect."""
    with pytest.raises(AppError) as exc_info:
        _detect_type("notes.txt", "application/pdf")

    assert exc_info.value.code == "DOCUMENT_TYPE_NOT_SUPPORTED"
    assert exc_info.value.status_code == 415


@pytest.mark.parametrize(
    "filename",
    ["script.py", "archive.zip", "image.png", "data.json", "noextension", "a.exe"],
)
def test_unsupported_extensions_are_rejected(filename: str) -> None:
    with pytest.raises(AppError) as exc_info:
        _detect_type(filename, "application/octet-stream")

    assert exc_info.value.code == "DOCUMENT_TYPE_NOT_SUPPORTED"
    assert exc_info.value.status_code == 415


def test_markdown_sent_as_plain_text_is_accepted() -> None:
    """Editors commonly report .md as text/plain."""
    assert _detect_type("readme.md", "text/plain") == DocumentType.MARKDOWN


# --- End-to-end processing --------------------------------------------------


def test_txt_upload_produces_document_data() -> None:
    result = process("notes.txt", "text/plain", b"Hello document world.")

    assert result.filename == "notes.txt"
    assert result.extension == ".txt"
    assert result.content_type == "text/plain"
    assert result.size_bytes == 21
    assert result.characters == len("Hello document world.")
    assert result.text == "Hello document world."
    assert result.metadata["encoding"] == "utf-8"


def test_pdf_upload_reports_page_metadata() -> None:
    result = process(
        "doc.pdf", "application/pdf", make_pdf(["Page one.", "Page two."])
    )

    assert result.extension == ".pdf"
    assert result.metadata["page_count"] == 2
    assert "Page one." in result.text


def test_docx_upload_reports_paragraph_and_table_metadata() -> None:
    result = process(
        "doc.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        make_docx(paragraphs=["Intro."], tables=[[["A", "B"]]]),
    )

    assert result.metadata["paragraph_count"] >= 1
    assert result.metadata["table_count"] == 1


def test_csv_upload_reports_row_and_column_metadata() -> None:
    result = process("data.csv", "text/csv", b"a,b\n1,2\n3,4")

    assert result.metadata["rows"] == 2
    assert result.metadata["columns"] == 2


def test_filename_is_sanitised_in_the_result() -> None:
    result = process("../../../etc/notes.txt", "text/plain", b"content")

    assert result.filename == "notes.txt"
    assert "/" not in result.filename


# --- Size limits ------------------------------------------------------------


def test_oversized_file_is_rejected() -> None:
    oversized = b"x" * (settings.max_upload_bytes + 1)

    with pytest.raises(AppError) as exc_info:
        process("big.txt", "text/plain", oversized)

    assert exc_info.value.code == "DOCUMENT_TOO_LARGE"
    assert exc_info.value.status_code == 413


def test_oversized_upload_is_rejected_before_full_buffering() -> None:
    """The read aborts part-way rather than materialising the whole file.

    Counted via a stream that records how many bytes were handed over.
    """

    class CountingUpload(FakeUpload):
        def __init__(self, size: int) -> None:
            super().__init__("big.txt", "text/plain", b"")
            self.remaining = size
            self.served = 0

        async def read(self, size: int = -1) -> bytes:
            chunk_size = min(size if size > 0 else 65536, self.remaining)
            self.remaining -= chunk_size
            self.served += chunk_size
            return b"x" * chunk_size

    upload = CountingUpload(settings.max_upload_bytes * 5)

    with pytest.raises(AppError) as exc_info:
        asyncio.run(document_service.process_upload(upload))

    assert exc_info.value.code == "DOCUMENT_TOO_LARGE"
    # Stopped shortly after crossing the limit, not after reading 50 MB.
    assert upload.served < settings.max_upload_bytes * 2


def test_empty_file_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        process("empty.txt", "text/plain", b"")

    assert exc_info.value.code == "DOCUMENT_INVALID"


def test_extracted_text_over_the_limit_is_rejected_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silent truncation would produce a summary of an invisibly cut document."""
    monkeypatch.setattr(settings, "DOCUMENT_MAX_EXTRACTED_CHARACTERS", 100)

    with pytest.raises(AppError) as exc_info:
        process("long.txt", "text/plain", b"y" * 500)

    assert exc_info.value.code == "DOCUMENT_CONTENT_TOO_LARGE"
    assert exc_info.value.status_code == 413


def test_text_exactly_at_the_limit_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_MAX_EXTRACTED_CHARACTERS", 100)

    result = process("ok.txt", "text/plain", b"y" * 100)

    assert result.characters == 100


# --- Empty document detection -----------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content_type", "data"),
    [
        ("blank.txt", "text/plain", b"   \n\n   "),
        ("blank.md", "text/markdown", b"\n\n\n"),
        ("blank.csv", "text/csv", b",,\n,,"),
    ],
    ids=["txt", "markdown", "csv"],
)
def test_documents_with_no_meaningful_text_are_reported(
    filename: str, content_type: str, data: bytes
) -> None:
    with pytest.raises(AppError) as exc_info:
        process(filename, content_type, data)

    assert exc_info.value.code == "DOCUMENT_TEXT_NOT_FOUND"
    assert exc_info.value.status_code == 422


def test_image_only_pdf_reports_no_text_and_mentions_ocr() -> None:
    with pytest.raises(AppError) as exc_info:
        process("scan.pdf", "application/pdf", make_pdf_without_text())

    assert exc_info.value.code == "DOCUMENT_TEXT_NOT_FOUND"
    assert "OCR" in exc_info.value.message


def test_empty_docx_reports_no_text() -> None:
    with pytest.raises(AppError) as exc_info:
        process("empty.docx", "application/zip", make_docx([]))

    assert exc_info.value.code == "DOCUMENT_TEXT_NOT_FOUND"


# --- Signature checks defeat a spoofed extension ----------------------------


def test_a_text_file_renamed_to_pdf_is_rejected() -> None:
    """Extension and MIME both say PDF; the bytes say otherwise."""
    with pytest.raises(AppError) as exc_info:
        process("fake.pdf", "application/pdf", b"I am plain text, not a PDF.")

    assert exc_info.value.code == "DOCUMENT_INVALID"


def test_a_text_file_renamed_to_docx_is_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        process("fake.docx", "application/zip", b"plain text")

    assert exc_info.value.code == "DOCUMENT_INVALID"


# --- No persistence, no AI --------------------------------------------------


def test_processing_does_not_touch_the_database() -> None:
    """Phase 7 stores nothing. MongoDB stays uninvolved."""
    from app.database import mongodb

    mongodb._client = None
    mongodb._connected = False

    result = process("notes.txt", "text/plain", b"content")

    assert result.text == "content"
    assert mongodb._client is None


def test_processing_does_not_call_groq(
    recorded_generate,
) -> None:
    """Upload and AI processing stay independent in this phase."""
    process("notes.txt", "text/plain", b"Some document content.")

    assert recorded_generate.calls == []
