"""Schemas for document upload and extraction.

Note what these models do NOT carry: no filesystem path, no temporary
filename, no server internals. `filename` is the name the client sent,
sanitised to a bare basename — never a path we resolved.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class DocumentType(str, Enum):
    """File types the extractor supports."""

    TXT = ".txt"
    MARKDOWN = ".md"
    CSV = ".csv"
    PDF = ".pdf"
    DOCX = ".docx"


# MIME types a client may plausibly send for each extension. Browsers, curl
# and OS file pickers disagree constantly, so each list is deliberately
# permissive — the extension is the primary signal, this is the cross-check.
ALLOWED_CONTENT_TYPES: dict[DocumentType, set[str]] = {
    DocumentType.TXT: {"text/plain"},
    DocumentType.MARKDOWN: {"text/markdown", "text/x-markdown", "text/plain"},
    DocumentType.CSV: {"text/csv", "application/csv", "text/plain"},
    DocumentType.PDF: {"application/pdf", "application/x-pdf"},
    DocumentType.DOCX: {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
}

# Sent when the client genuinely does not know the type. Not a mismatch, so
# these fall through to extension-based validation.
GENERIC_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/download",
}


class DocumentData(BaseModel):
    """`data` payload returned by POST /api/documents/upload."""

    filename: str = Field(description="Sanitised original filename, no path.")
    extension: str = Field(description="Detected file extension, e.g. '.pdf'.")
    content_type: str = Field(description="MIME type reported by the client.")
    size_bytes: int = Field(ge=0, description="Size of the uploaded file.")
    characters: int = Field(ge=0, description="Length of the extracted text.")
    text: str = Field(description="Normalised extracted text.")
    metadata: dict = Field(
        default_factory=dict,
        description="Safe format-specific metadata, e.g. page_count.",
    )


# --- Persisted documents (Phase 14) -----------------------------------------

# A title is a display label, not content.
MAX_TITLE_CHARS = 200

# Pagination bounds, matching the conversation list.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

TitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS),
]


class RenameDocumentRequest(BaseModel):
    """PATCH /api/documents/{id}

    Title is the only mutable field. `filename` records what was actually
    uploaded and stays immutable, so renaming never rewrites history.
    """

    title: TitleText


class DocumentSummary(BaseModel):
    """One document in a listing.

    Deliberately without `text`: a page of twenty documents could otherwise
    carry two megabytes of extracted content nobody asked for.
    """

    id: str
    title: str
    filename: str
    extension: str
    content_type: str
    size_bytes: int = Field(ge=0)
    characters: int = Field(ge=0)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StoredDocumentData(DocumentSummary):
    """A single document, including its extracted text."""

    text: str


class DocumentListData(BaseModel):
    """GET /api/documents — one page of the caller's own documents."""

    documents: list[DocumentSummary]
    page: int
    page_size: int
    total: int
    has_more: bool
