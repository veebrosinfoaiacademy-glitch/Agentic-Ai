"""Document endpoints.

Upload validates and extracts in memory, then persists the extracted text so
the document can be reopened and reused. The original binary is never written
anywhere — not to disk, not to the database.

Thin by design: no parsing, no database queries, no AI call. None of these
routes consumes AI quota; only sending a document to an agent does, through
the existing conversation endpoint.
"""

import logging

from fastapi import APIRouter, File, Query, UploadFile, status

from app.config import settings
from app.dependencies.auth import CurrentUser
from app.schemas.common_schemas import SuccessResponse, success
from app.schemas.document_schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    DocumentType,
    RenameDocumentRequest,
)
from app.services.document_service import document_repository, document_service

logger = logging.getLogger("app.routes.documents")

router = APIRouter(tags=["Documents"])

_NOT_FOUND = {"description": "No such document, or it belongs to another user"}


@router.post(
    "/upload",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document and extract its text",
    description=(
        "Accepts **.txt**, **.md**, **.csv**, **.pdf** and **.docx** files, "
        "extracts the text, and stores it against your account so it can be "
        "reused later.\n\n"
        "The uploaded file itself is processed in memory and **discarded** — "
        "only the extracted text and safe metadata are kept. No OCR is "
        "performed, so scanned or image-only PDFs return "
        "`DOCUMENT_TEXT_NOT_FOUND`. Uploaded files are never executed.\n\n"
        "Uses no AI quota."
    ),
    responses={
        413: {"description": "File too large, or extracted text exceeds the limit"},
        415: {"description": "Unsupported file type, or type/extension mismatch"},
        422: {"description": "Unreadable, corrupt, or containing no text"},
        503: {"description": "The document could not be stored"},
    },
)
async def upload_document(
    user: CurrentUser,
    file: UploadFile = File(
        ...,
        description="Document to process (.txt, .md, .csv, .pdf, .docx).",
    ),
) -> dict:
    """Extract text from an uploaded document and persist it.

    Authentication is resolved before the file is read, so an anonymous
    request never reaches the extractor.
    """
    extracted = await document_service.process_upload(file)
    stored = document_repository.save(user_id=user.id, extracted=extracted)

    return success(
        data=stored.model_dump(mode="json"),
        message="Document processed successfully",
    )


@router.get(
    "",
    response_model=SuccessResponse,
    summary="List your documents",
    description=(
        "Returns only the signed-in user's documents, newest first. The "
        "extracted text is **not** included — fetch a single document for "
        "that. Uses no AI quota."
    ),
)
def list_documents(
    user: CurrentUser,
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Documents per page (max {MAX_PAGE_SIZE}).",
    ),
) -> dict:
    listing = document_repository.list_for_user(
        user_id=user.id, page=page, page_size=page_size
    )
    return success(
        data=listing.model_dump(mode="json"),
        message="Documents retrieved successfully",
    )


@router.get(
    "/supported-types",
    response_model=SuccessResponse,
    summary="List supported document types and limits",
    description="Lets a client show accurate upload rules without hardcoding them.",
)
def supported_types() -> dict:
    """Report what the upload endpoint accepts.

    Served from configuration so the API and any UI cannot disagree about
    the limits. Public: global server configuration, no user data.
    """
    return success(
        data={
            "extensions": [t.value for t in DocumentType],
            "max_file_size_mb": settings.MAX_UPLOAD_MB,
            "max_extracted_characters": settings.DOCUMENT_MAX_EXTRACTED_CHARACTERS,
            "ocr_supported": False,
        },
        message="Supported document types retrieved",
    )


@router.get(
    "/{document_id}",
    response_model=SuccessResponse,
    summary="Get a document and its extracted text",
    description="Uses no AI quota.",
    responses={404: _NOT_FOUND},
)
def get_document(document_id: str, user: CurrentUser) -> dict:
    document = document_repository.get_detail(
        user_id=user.id, document_id=document_id
    )
    return success(
        data=document.model_dump(mode="json"),
        message="Document retrieved successfully",
    )


@router.patch(
    "/{document_id}",
    response_model=SuccessResponse,
    summary="Rename a document",
    description=(
        "Changes the display title only. The original `filename` is immutable, "
        "so a rename never rewrites what was actually uploaded."
    ),
    responses={404: _NOT_FOUND},
)
def rename_document(
    document_id: str, request: RenameDocumentRequest, user: CurrentUser
) -> dict:
    document = document_repository.rename(
        user_id=user.id, document_id=document_id, title=request.title
    )
    return success(
        data=document.model_dump(mode="json"),
        message="Document renamed successfully",
    )


@router.delete(
    "/{document_id}",
    response_model=SuccessResponse,
    summary="Delete a document",
    description=(
        "Removes the stored text and metadata. Conversation messages that "
        "already used this document keep the filename recorded at the time, "
        "so past transcripts stay readable."
    ),
    responses={404: _NOT_FOUND},
)
def delete_document(document_id: str, user: CurrentUser) -> dict:
    document_repository.delete(user_id=user.id, document_id=document_id)
    return success(data=None, message="Document deleted successfully")
