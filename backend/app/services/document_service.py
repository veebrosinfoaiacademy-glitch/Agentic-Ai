"""Document upload orchestration.

Owns the whole pipeline for one upload:

    validate name -> validate type -> read with a size ceiling
    -> pick extractor -> extract -> check the text is usable -> build result

Deliberately does NOT call Groq. Upload and AI processing stay independent so
a later phase can feed `DocumentData.text` into the Content Agent without
this service needing to know that agents exist.
"""

import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable, Protocol

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from app.config import settings
from app.database import get_documents_collection
from app.schemas.document_schemas import (
    ALLOWED_CONTENT_TYPES,
    GENERIC_CONTENT_TYPES,
    DocumentData,
    DocumentListData,
    DocumentSummary,
    DocumentType,
    StoredDocumentData,
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


# --- Persistence (Phase 14) -------------------------------------------------
#
# Extraction above is unchanged: the binary is read in memory, validated,
# turned into normalised text, and discarded. What is new is that the text
# and its metadata are kept, so a document can be reopened and reused.
#
# The original file is still never written anywhere.


def _document_not_found() -> AppError:
    """The document does not exist, or belongs to someone else.

    One error for both, deliberately. Distinguishing them would turn these
    endpoints into an oracle for which ids exist, so a caller asking about
    another account's document gets exactly what they would get for an id
    that was never issued.
    """
    return AppError(
        code="DOCUMENT_NOT_FOUND",
        message="Document not found",
        status_code=404,
    )


def _document_database_unavailable(exc: PyMongoError) -> AppError:
    """MongoDB could not answer.

    Never claims a document was stored when the write failed, and never
    surfaces the PyMongo message, which carries cluster hostnames.
    """
    logger.error("Document database operation failed: %s", type(exc).__name__)
    return AppError(
        code="DATABASE_UNAVAILABLE",
        message="The service is temporarily unavailable. Please try again.",
        status_code=503,
    )


def _to_object_id(value: str, label: str) -> ObjectId:
    """Parse an id from a URL, failing cleanly rather than with a 500.

    ObjectId(None) does NOT raise — it silently generates a new random id —
    so the type check has to come first.
    """
    if not isinstance(value, str) or not value.strip():
        raise AppError(code="INVALID_ID", message=f"Invalid {label} id", status_code=422)
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        logger.info("Rejected malformed %s id", label)
        raise AppError(
            code="INVALID_ID", message=f"Invalid {label} id", status_code=422
        ) from None


def _summary_fields(document: dict) -> dict:
    """The public shape of a stored document, minus its text.

    Fields are named explicitly rather than filtered, so a field added to the
    stored document later cannot leak by omission. `user_id` never crosses
    this boundary.
    """
    return {
        "id": str(document["_id"]),
        "title": document["title"],
        "filename": document["filename"],
        "extension": document["extension"],
        "content_type": document["content_type"],
        "size_bytes": document["size_bytes"],
        "characters": document["characters"],
        "metadata": document.get("metadata", {}),
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
    }


class DocumentRepository:
    """Stores and retrieves documents, always scoped to one user."""

    @staticmethod
    def _owned(document_id: ObjectId, user_id: ObjectId) -> dict:
        """The only filter used to reach a document.

        Ownership is part of the query, not a check performed afterwards on
        the result. A find_one({"_id": ...}) followed by an `if` is one
        forgotten branch away from an IDOR; this cannot return another
        user's row at all.
        """
        return {"_id": document_id, "user_id": user_id}

    def save(self, user_id: str, extracted: DocumentData) -> StoredDocumentData:
        """Persist an extracted document for the authenticated user."""
        owner = _to_object_id(user_id, "user")
        now = datetime.now(UTC)

        document = {
            "user_id": owner,
            # Sanitised at extraction time; the display label starts as the
            # filename and is the only thing a rename can change.
            "filename": extracted.filename,
            "title": extracted.filename,
            "extension": extracted.extension,
            "content_type": extracted.content_type,
            "size_bytes": extracted.size_bytes,
            "characters": extracted.characters,
            "text": extracted.text,
            "metadata": extracted.metadata,
            "created_at": now,
            "updated_at": now,
        }

        try:
            result = get_documents_collection().insert_one(document)
        except PyMongoError as exc:
            raise _document_database_unavailable(exc) from None

        document["_id"] = result.inserted_id
        logger.info(
            "Document %s stored for user %s (%d characters)",
            result.inserted_id,
            owner,
            extracted.characters,
        )
        return StoredDocumentData(**_summary_fields(document), text=document["text"])

    def list_for_user(
        self, user_id: str, page: int, page_size: int
    ) -> DocumentListData:
        """One page of the caller's documents, newest first."""
        owner = _to_object_id(user_id, "user")
        collection = get_documents_collection()
        query = {"user_id": owner}

        try:
            total = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("created_at", -1)
                .skip((page - 1) * page_size)
                .limit(page_size)
            )
            documents = list(cursor)
        except PyMongoError as exc:
            raise _document_database_unavailable(exc) from None

        return DocumentListData(
            documents=[DocumentSummary(**_summary_fields(d)) for d in documents],
            page=page,
            page_size=page_size,
            total=total,
            has_more=(page * page_size) < total,
        )

    def get_owned(self, user_id: str, document_id: str) -> dict:
        """Fetch the raw stored document the caller owns, or raise 404.

        Returns the document rather than a schema because callers need
        different slices of it — the detail endpoint wants everything, the
        conversation integration wants only the text.
        """
        oid = _to_object_id(document_id, "document")
        owner = _to_object_id(user_id, "user")

        try:
            document = get_documents_collection().find_one(self._owned(oid, owner))
        except PyMongoError as exc:
            raise _document_database_unavailable(exc) from None

        if document is None:
            logger.info("Document lookup miss or not owned by the caller")
            raise _document_not_found()
        return document

    def get_detail(self, user_id: str, document_id: str) -> StoredDocumentData:
        """A document including its extracted text."""
        document = self.get_owned(user_id, document_id)
        return StoredDocumentData(
            **_summary_fields(document), text=document.get("text", "")
        )

    def rename(self, user_id: str, document_id: str, title: str) -> DocumentSummary:
        """Change a document's display title. Nothing else is mutable."""
        oid = _to_object_id(document_id, "document")
        owner = _to_object_id(user_id, "user")

        try:
            document = get_documents_collection().find_one_and_update(
                self._owned(oid, owner),
                # An explicit field list, so a crafted request cannot reach
                # user_id, filename, text or created_at.
                {"$set": {"title": title, "updated_at": datetime.now(UTC)}},
                return_document=True,
            )
        except PyMongoError as exc:
            raise _document_database_unavailable(exc) from None

        if document is None:
            raise _document_not_found()

        logger.info("Document %s renamed", oid)
        return DocumentSummary(**_summary_fields(document))

    def delete(self, user_id: str, document_id: str) -> None:
        """Delete a document the caller owns.

        Past conversation messages that referenced it are deliberately left
        alone: they keep the filename recorded at the time, so a transcript
        stays readable. History is not rewritten by a later deletion.
        """
        oid = _to_object_id(document_id, "document")
        owner = _to_object_id(user_id, "user")

        try:
            result = get_documents_collection().delete_one(self._owned(oid, owner))
        except PyMongoError as exc:
            raise _document_database_unavailable(exc) from None

        if result.deleted_count == 0:
            raise _document_not_found()

        logger.info("Document %s deleted", oid)


document_repository = DocumentRepository()
