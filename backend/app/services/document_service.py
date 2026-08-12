"""Document upload orchestration.

Owns the whole pipeline for one upload:

    validate name -> validate type -> read with a size ceiling
    -> pick extractor -> extract -> check the text is usable -> build result

Deliberately does NOT call Groq. Upload and AI processing stay independent so
a later phase can feed `DocumentData.text` into the Content Agent without
this service needing to know that agents exist.
"""

import logging
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable, Protocol

from app.config import settings
from app.schemas.document_schemas import (
    ALLOWED_CONTENT_TYPES,
    GENERIC_CONTENT_TYPES,
    DocumentData,
    DocumentType,
)
from app.utils.document_extractors import (
    extract_csv,
    extract_docx,
    extract_markdown,
    extract_pdf,
    extract_txt,
)
from app.utils.errors import AppError

logger = logging.getLogger("app.documents")

# Read in 64 KB chunks so an oversized upload is rejected part-way through
# rather than after the whole thing is in memory.
CHUNK_SIZE = 64 * 1024

EXTRACTORS: dict[DocumentType, Callable[[bytes], tuple[str, dict]]] = {
    DocumentType.TXT: extract_txt,
    DocumentType.MARKDOWN: extract_markdown,
    DocumentType.CSV: extract_csv,
    DocumentType.PDF: extract_pdf,
    DocumentType.DOCX: extract_docx,
}

# Every MIME type we recognise, used to tell "client sent a generic type" from
# "client sent a type that contradicts the extension".
_KNOWN_CONTENT_TYPES = {
    value for values in ALLOWED_CONTENT_TYPES.values() for value in values
}


class UploadLike(Protocol):
    """The part of FastAPI's UploadFile this service actually uses.

    Typed structurally so tests can pass a simple stand-in and the service
    stays independent of the web framework.
    """

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...


def _sanitize_filename(raw: str | None) -> str:
    """Reduce a client-supplied filename to a bare, safe basename.

    A filename is attacker-controlled. "../../etc/passwd" and
    "C:\\Windows\\system32\\x.txt" both collapse to their last component here.
    Nothing downstream opens this path — we never write the file — but the
    name is echoed back in the response, and a path there would be both a
    leak and a trap for any client that trusts it.
    """
    if not raw or not raw.strip():
        raise AppError(
            code="DOCUMENT_INVALID",
            message="The uploaded file has no filename.",
            status_code=422,
        )

    # Handle both separators regardless of the server's OS.
    name = PureWindowsPath(PurePosixPath(raw.strip()).name).name
    name = name.replace("\x00", "").strip()

    if not name or name in {".", ".."}:
        raise AppError(
            code="DOCUMENT_INVALID",
            message="The uploaded file has an invalid filename.",
            status_code=422,
        )
    return name


def _detect_type(filename: str, content_type: str | None) -> DocumentType:
    """Determine the document type from the extension, cross-checked by MIME.

    The extension decides which parser to use; the MIME type can only veto.
    Trusting MIME alone is unsafe because a client sets it freely, and
    trusting the extension alone means "invoice.pdf" containing a ZIP gets
    handed to the PDF parser. Extractors additionally verify file signatures,
    which is the check that actually cannot be spoofed by metadata.
    """
    suffix = PurePosixPath(filename).suffix.lower()

    try:
        document_type = DocumentType(suffix)
    except ValueError:
        supported = ", ".join(t.value for t in DocumentType)
        raise AppError(
            code="DOCUMENT_TYPE_NOT_SUPPORTED",
            message=f"Unsupported file type '{suffix or 'unknown'}'. Supported: {supported}",
            status_code=415,
        ) from None

    declared = (content_type or "").split(";")[0].strip().lower()

    # Unknown or generic types tell us nothing, so the extension stands.
    if declared in GENERIC_CONTENT_TYPES or declared not in _KNOWN_CONTENT_TYPES:
        return document_type

    if declared not in ALLOWED_CONTENT_TYPES[document_type]:
        raise AppError(
            code="DOCUMENT_TYPE_NOT_SUPPORTED",
            message=(
                f"The file type '{declared}' does not match the '{suffix}' extension."
            ),
            status_code=415,
        )

    return document_type


async def _read_with_limit(upload: UploadLike, max_bytes: int) -> bytes:
    """Read the upload, aborting as soon as it exceeds the size limit.

    Chunked rather than a single read() so a 500 MB upload is refused after
    the first chunk over the line, instead of being fully buffered first.
    """
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break

        total += len(chunk)
        if total > max_bytes:
            logger.warning("Upload rejected: exceeds %d bytes", max_bytes)
            raise AppError(
                code="DOCUMENT_TOO_LARGE",
                message=(
                    f"The file is larger than the {settings.MAX_UPLOAD_MB} MB limit."
                ),
                status_code=413,
            )
        chunks.append(chunk)

    if total == 0:
        raise AppError(
            code="DOCUMENT_INVALID",
            message="The uploaded file is empty.",
            status_code=422,
        )

    return b"".join(chunks)


class DocumentService:
    """Turns an uploaded file into normalised text plus safe metadata."""

    async def process_upload(self, upload: UploadLike) -> DocumentData:
        """Validate, extract and normalise one uploaded document.

        Raises:
            AppError: for every failure mode, already mapped to an HTTP status.
        """
        filename = _sanitize_filename(upload.filename)
        document_type = _detect_type(filename, upload.content_type)

        data = await _read_with_limit(upload, settings.max_upload_bytes)

        logger.info(
            "Processing %s upload: %d bytes", document_type.value, len(data)
        )

        text, metadata = EXTRACTORS[document_type](data)

        if not text.strip():
            # Reported rather than passed on: sending an empty prompt to Groq
            # wastes a call and returns a confidently wrong answer about
            # nothing.
            raise AppError(
                code="DOCUMENT_TEXT_NOT_FOUND",
                message=(
                    "No readable text was found in the document. Scanned or "
                    "image-only files are not supported, as this system does "
                    "not perform OCR."
                ),
                status_code=422,
            )

        limit = settings.DOCUMENT_MAX_EXTRACTED_CHARACTERS
        if len(text) > limit:
            # Not truncated silently: a summary of an invisibly cut document
            # is misleading, so the caller is told and can decide.
            logger.warning("Extracted text too large: %d > %d", len(text), limit)
            raise AppError(
                code="DOCUMENT_CONTENT_TOO_LARGE",
                message=(
                    f"The document contains {len(text):,} characters, which "
                    f"exceeds the {limit:,} character limit."
                ),
                status_code=413,
            )

        logger.info(
            "Extracted %d characters from %s", len(text), document_type.value
        )

        return DocumentData(
            filename=filename,
            extension=document_type.value,
            content_type=(upload.content_type or "").split(";")[0].strip(),
            size_bytes=len(data),
            characters=len(text),
            text=text,
            metadata=metadata,
        )


# Single shared instance, matching the project's service pattern.
document_service = DocumentService()
