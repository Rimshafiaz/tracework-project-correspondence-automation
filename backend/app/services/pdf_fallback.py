from hashlib import sha256

from pydantic import ValidationError

from app.contracts.attachment_content import HashedAttachmentContent
from app.contracts.attachment_extraction import AttachmentExtractionMetadata, ExtractionMethod, ExtractionReason, GeminiPDFFallbackRequest
from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState


class PDFFallbackEligibilityError(ValueError):
    pass


def build_pdf_fallback_request(
    attachment: Attachment,
    content: HashedAttachmentContent,
) -> GeminiPDFFallbackRequest:
    if attachment.processing_state is not AttachmentProcessingState.FALLBACK_REQUIRED:
        raise PDFFallbackEligibilityError("attachment is not marked FALLBACK_REQUIRED")
    if not attachment.filename.casefold().endswith(".pdf") or attachment.mime_type.casefold() != "application/pdf":
        raise PDFFallbackEligibilityError("attachment is not a PDF")
    if attachment.id != content.attachment_id or attachment.content_hash != content.content_hash:
        raise PDFFallbackEligibilityError("attachment content identity does not match")
    if sha256(content.content).hexdigest() != content.content_hash:
        raise PDFFallbackEligibilityError("attachment bytes do not match the content hash")
    try:
        metadata = AttachmentExtractionMetadata.model_validate(attachment.extraction_metadata)
    except ValidationError as error:
        raise PDFFallbackEligibilityError("attachment extraction metadata is invalid") from error
    if metadata.extraction_method is not ExtractionMethod.PYMUPDF or metadata.reason not in {
        ExtractionReason.PDF_IMAGE_ONLY,
        ExtractionReason.PDF_PARTIAL_IMAGE_TEXT,
    }:
        raise PDFFallbackEligibilityError("attachment does not have eligible PDF fallback metadata")

    return GeminiPDFFallbackRequest(
        attachment_id=attachment.id,
        content_hash=content.content_hash,
        content=content.content,
        reason=metadata.reason,
        partial_extracted_text=attachment.extracted_text,
        pdf_segments=metadata.pdf_segments,
    )
