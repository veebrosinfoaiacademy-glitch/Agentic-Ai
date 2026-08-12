"""Phase 7 tests: text extraction from each supported format.

Every document used here is built in memory. No checked-in binary fixtures,
no files from anyone's machine.
"""

import pytest

from app.utils.document_extractors import (
    extract_csv,
    extract_docx,
    extract_markdown,
    extract_pdf,
    extract_txt,
    normalize_text,
)
from app.utils.errors import AppError
from tests.conftest import (
    make_docx,
    make_docx_interleaved,
    make_pdf,
    make_pdf_without_text,
)


# --- Normalisation ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a\r\n\r\nb", "a\n\nb"),
        ("a\x00b", "ab"),
        ("  padded  ", "padded"),
        ("trailing   \nspaces  ", "trailing\nspaces"),
        ("", ""),
    ],
    ids=["crlf", "cr", "crlf-blank", "null-byte", "trim", "line-trim", "empty"],
)
def test_normalization_cleans_without_destroying_content(
    raw: str, expected: str
) -> None:
    assert normalize_text(raw) == expected


def test_normalization_collapses_long_blank_runs_but_keeps_paragraphs() -> None:
    """Paragraph separation must survive — it is structure, not noise."""
    result = normalize_text("Para one.\n\n\n\n\nPara two.")

    assert result == "Para one.\n\nPara two."


def test_normalization_preserves_indentation() -> None:
    """Leading whitespace carries meaning in code blocks and nested lists."""
    assert normalize_text("def f():\n    return 1") == "def f():\n    return 1"


# --- TXT --------------------------------------------------------------------


def test_txt_extracts_plain_text() -> None:
    text, metadata = extract_txt(b"Hello world.\nSecond line.")

    assert text == "Hello world.\nSecond line."
    assert metadata["encoding"] == "utf-8"


def test_txt_strips_a_utf8_bom() -> None:
    """A BOM would otherwise appear as a stray character at position 0."""
    text, _ = extract_txt(b"\xef\xbb\xbfHello with BOM")

    assert text == "Hello with BOM"
    assert not text.startswith("﻿")


def test_txt_normalizes_windows_line_endings() -> None:
    text, _ = extract_txt(b"line one\r\nline two\r\n")

    assert "\r" not in text
    assert text == "line one\nline two"


def test_txt_removes_null_bytes() -> None:
    text, _ = extract_txt(b"clean\x00text")

    assert text == "cleantext"


def test_txt_handles_unicode() -> None:
    text, _ = extract_txt("Café — naïve — 日本語".encode())

    assert "Café" in text
    assert "日本語" in text


def test_txt_rejects_invalid_encoding_rather_than_corrupting() -> None:
    """Silent replacement characters would be worse than a clear failure."""
    with pytest.raises(AppError) as exc_info:
        extract_txt(b"\xff\xfe\x00invalid utf8 \xc3\x28")

    assert exc_info.value.code == "DOCUMENT_INVALID"
    assert exc_info.value.status_code == 422


def test_empty_txt_yields_empty_text() -> None:
    """The service decides this is DOCUMENT_TEXT_NOT_FOUND, not the extractor."""
    text, _ = extract_txt(b"   \n\n  ")

    assert text == ""


# --- Markdown ---------------------------------------------------------------


def test_markdown_preserves_syntax() -> None:
    """Markers are structure. Converting to HTML would discard it."""
    source = b"# Title\n\n- one\n- two\n\n**bold** and `code`"

    text, metadata = extract_markdown(source)

    assert "# Title" in text
    assert "- one" in text
    assert "**bold**" in text
    assert "`code`" in text
    assert "<h1>" not in text
    assert metadata["heading_count"] == 1


def test_markdown_counts_headings_at_any_level() -> None:
    _, metadata = extract_markdown(b"# A\n\n## B\n\n### C\n\ntext")

    assert metadata["heading_count"] == 3


def test_empty_markdown_yields_empty_text() -> None:
    text, _ = extract_markdown(b"\n\n   \n")

    assert text == ""


# --- CSV --------------------------------------------------------------------


def test_csv_renders_a_readable_table() -> None:
    text, metadata = extract_csv(b"name,age,city\nAlice,22,Chennai\nBob,25,Bangalore")

    assert "Header: name, age, city" in text
    assert "Rows:" in text
    assert "Alice | 22 | Chennai" in text
    assert "Bob | 25 | Bangalore" in text
    assert metadata == {"rows": 2, "columns": 3, "has_header": True}


def test_csv_is_not_a_python_repr() -> None:
    """Guards against someone "simplifying" this to str(list_of_rows)."""
    text, _ = extract_csv(b"a,b\n1,2")

    assert "[" not in text
    assert "'" not in text


def test_csv_handles_commas_inside_quoted_fields() -> None:
    text, metadata = extract_csv(b'name,address\n"Smith, John","12 High St, Chennai"')

    assert "Smith, John" in text
    assert "12 High St, Chennai" in text
    assert metadata["rows"] == 1
    assert metadata["columns"] == 2


def test_csv_handles_quoted_newlines_and_escaped_quotes() -> None:
    text, metadata = extract_csv(b'quote,who\n"He said ""hi""",Bob')

    assert 'He said "hi"' in text
    assert metadata["rows"] == 1


def test_csv_with_headers_only_still_yields_text() -> None:
    """Column names are real extracted content, so this is not "empty"."""
    text, metadata = extract_csv(b"name,age,city\n")

    assert "Header: name, age, city" in text
    assert "Rows:" not in text
    assert metadata["rows"] == 0
    assert metadata["columns"] == 3


def test_empty_csv_yields_empty_text() -> None:
    text, metadata = extract_csv(b"")

    assert text == ""
    assert metadata == {"rows": 0, "columns": 0}


def test_csv_of_only_blank_rows_yields_empty_text() -> None:
    text, metadata = extract_csv(b",,\n,,\n")

    assert text == ""
    assert metadata["rows"] == 0


def test_csv_keeps_ragged_rows_rather_than_dropping_them() -> None:
    """A short row usually means missing data, which is worth showing."""
    text, metadata = extract_csv(b"a,b,c\n1,2,3\n4,5\n6,7,8,9")

    assert "4 | 5" in text
    assert "6 | 7 | 8 | 9" in text
    assert metadata["rows"] == 3
    assert metadata["columns"] == 4


def test_csv_formula_cells_are_treated_as_text() -> None:
    """A leading "=" is a formula to a spreadsheet. Here it is just a string."""
    text, _ = extract_csv(b'formula,value\n"=SUM(A1:A9)",10')

    assert "=SUM(A1:A9)" in text


def test_csv_truncates_an_enormous_cell() -> None:
    huge = b"col\n" + b"x" * 2000

    text, _ = extract_csv(huge)

    assert "..." in text
    assert len(text) < 1000


# --- PDF --------------------------------------------------------------------


def test_pdf_extracts_text_from_a_single_page() -> None:
    text, metadata = extract_pdf(make_pdf(["Hello from the only page."]))

    assert "Hello from the only page." in text
    assert metadata["page_count"] == 1


def test_pdf_marks_page_boundaries() -> None:
    text, metadata = extract_pdf(
        make_pdf(["First page text.", "Second page text.", "Third page text."])
    )

    assert "--- Page 1 ---" in text
    assert "--- Page 2 ---" in text
    assert "--- Page 3 ---" in text
    assert "First page text." in text
    assert "Third page text." in text
    assert metadata["page_count"] == 3
    assert metadata["pages_with_text"] == 3


def test_pdf_reports_page_count_including_empty_pages() -> None:
    """page_count is the document's page count; pages_with_text is what we read."""
    text, metadata = extract_pdf(make_pdf_without_text(page_count=4))

    assert text == ""
    assert metadata["page_count"] == 4
    assert metadata["pages_with_text"] == 0


def test_image_only_pdf_yields_no_text_rather_than_pretending_ocr() -> None:
    text, _ = extract_pdf(make_pdf_without_text())

    assert text == ""


def test_pdf_rejects_bytes_that_are_not_a_pdf() -> None:
    """Signature check: the extension said PDF, the bytes disagree."""
    with pytest.raises(AppError) as exc_info:
        extract_pdf(b"this is definitely not a pdf")

    assert exc_info.value.code == "DOCUMENT_INVALID"


def test_pdf_rejects_a_truncated_file() -> None:
    corrupt = make_pdf(["some text"])[:120]

    with pytest.raises(AppError) as exc_info:
        extract_pdf(corrupt)

    assert exc_info.value.code in {"DOCUMENT_INVALID", "DOCUMENT_EXTRACTION_FAILED"}


# --- DOCX -------------------------------------------------------------------


def test_docx_extracts_paragraphs() -> None:
    text, metadata = extract_docx(
        make_docx(["First paragraph.", "Second paragraph.", "Third paragraph."])
    )

    assert "First paragraph." in text
    assert "Third paragraph." in text
    assert metadata["paragraph_count"] == 3
    assert metadata["table_count"] == 0


def test_docx_extracts_table_contents() -> None:
    text, metadata = extract_docx(
        make_docx(
            paragraphs=["Intro."],
            tables=[[["Name", "Role"], ["Alice", "Engineer"]]],
        )
    )

    assert "Name | Role" in text
    assert "Alice | Engineer" in text
    assert metadata["table_count"] == 1


def test_docx_preserves_reading_order_of_paragraphs_and_tables() -> None:
    """python-docx lists paragraphs and tables separately, losing their order.

    Walking the body XML keeps a table where the author actually put it. The
    document here really does have the table between the two paragraphs, so
    naive `.paragraphs + .tables` extraction would put INSIDE last and fail.
    """
    text, metadata = extract_docx(
        make_docx_interleaved(
            [
                ("p", "BEFORE the table."),
                ("table", [["INSIDE", "TABLE"]]),
                ("p", "AFTER the table."),
            ]
        )
    )

    before = text.index("BEFORE the table.")
    inside = text.index("INSIDE")
    after = text.index("AFTER the table.")

    assert before < inside < after
    assert metadata["paragraph_count"] == 2
    assert metadata["table_count"] == 1


def test_docx_skips_empty_paragraphs_in_the_text() -> None:
    text, metadata = extract_docx(make_docx(["Real content.", "", "   ", "More."]))

    assert "Real content." in text
    assert "More." in text
    assert metadata["paragraph_count"] == 4  # counted
    assert text.count("\n\n") == 1  # but not emitted as blank blocks


def test_empty_docx_yields_no_text() -> None:
    text, metadata = extract_docx(make_docx([]))

    assert text == ""
    assert metadata["table_count"] == 0


def test_docx_rejects_bytes_that_are_not_a_zip() -> None:
    with pytest.raises(AppError) as exc_info:
        extract_docx(b"not a docx at all")

    assert exc_info.value.code == "DOCUMENT_INVALID"


def test_docx_rejects_a_zip_that_is_not_a_word_document() -> None:
    """Correct ZIP signature, wrong contents — caught by python-docx."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a word document")

    with pytest.raises(AppError) as exc_info:
        extract_docx(buffer.getvalue())

    assert exc_info.value.code in {"DOCUMENT_INVALID", "DOCUMENT_EXTRACTION_FAILED"}


def test_docx_rejects_a_truncated_file() -> None:
    with pytest.raises(AppError) as exc_info:
        extract_docx(make_docx(["text"])[:100])

    assert exc_info.value.code in {"DOCUMENT_INVALID", "DOCUMENT_EXTRACTION_FAILED"}


# --- Error messages stay clean ----------------------------------------------


@pytest.mark.parametrize(
    "extractor", [extract_pdf, extract_docx], ids=["pdf", "docx"]
)
def test_parser_errors_do_not_leak_internals(extractor) -> None:
    """No file paths, module names or tracebacks in a client-facing message."""
    with pytest.raises(AppError) as exc_info:
        extractor(b"garbage bytes that will not parse")

    message = exc_info.value.message
    for leak in ("/Users/", "Traceback", "site-packages", ".py", "0x"):
        assert leak not in message
