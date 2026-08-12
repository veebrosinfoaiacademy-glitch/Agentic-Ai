"""Document upload endpoint.

Thin: hand the upload to the service, wrap the result. No parsing here, and
no AI call — extraction is deliberately independent of the agents so a later
phase can pipe the text wherever it likes.
"""

import logging

from fastapi import APIRouter, File, UploadFile

from app.config import settings
from app.dependencies.auth import CurrentUser
from app.schemas.common_schemas import SuccessResponse, success
from app.schemas.document_schemas import DocumentType
from app.services.document_service import document_service

logger = logging.getLogger("app.routes.documents")

router = APIRouter(tags=["Documents"])


@router.post(
    "/upload",
    response_model=SuccessResponse,
    summary="Upload a document and extract its text",
    description=(
        "Accepts **.txt**, **.md**, **.csv**, **.pdf** and **.docx** files and "
        "returns the extracted, normalised text plus safe format-specific "
        "metadata (page count, paragraph and table counts, row and column "
        "counts).\n\n"
        "The file is processed entirely in memory and is **not stored**. No "
        "OCR is performed, so scanned or image-only PDFs return "
        "`DOCUMENT_TEXT_NOT_FOUND`. Uploaded files are never executed."
    ),
    responses={
        413: {"description": "File too large, or extracted text exceeds the limit"},
        415: {"description": "Unsupported file type, or type/extension mismatch"},
        422: {"description": "Unreadable, corrupt, or containing no text"},
    },
)
async def upload_document(
    user: CurrentUser,
    file: UploadFile = File(
        ...,
        description="Document to process (.txt, .md, .csv, .pdf, .docx).",
    ),
) -> dict:
    """Extract text from an uploaded document.

    Authentication is resolved before the file is read, so an anonymous
    request never reaches the extractor.
    """
    result = await document_service.process_upload(file)

    return success(
        data=result.model_dump(),
        message="Document processed successfully",
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
    the limits.
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
