from pathlib import Path

from app.contracts.attachment_content import HashedAttachmentContent
from app.contracts.attachment_extraction import AttachmentExtractionResult, ExtractionMethod, ExtractionReason
from app.core.config import Settings
from app.models.enums import AttachmentProcessingState
from app.services.docx_extraction import DOCX_MIME_TYPE, extract_docx
from app.services.pdf_extraction import PDFExtractionError, extract_pdf
from app.services.pdf_quality import classify_pdf_extraction

PDF_MIME_TYPE = "application/pdf"


def process_attachment(
    content: HashedAttachmentContent,
    *,
    filename: str,
    mime_type: str,
    settings: Settings,
) -> AttachmentExtractionResult:
    if not content.content:
        return _terminal_result(content, AttachmentProcessingState.FAILED, ExtractionReason.EMPTY_ATTACHMENT)
    if content.size_bytes > settings.attachment_max_size_bytes:
        return _terminal_result(content, AttachmentProcessingState.FAILED, ExtractionReason.ATTACHMENT_TOO_LARGE)

    extension = Path(filename).suffix.casefold()
    normalized_mime = mime_type.casefold()
    is_pdf_signal = extension == ".pdf" or normalized_mime == PDF_MIME_TYPE
    is_docx_signal = extension == ".docx" or normalized_mime == DOCX_MIME_TYPE

    if is_pdf_signal and is_docx_signal:
        return _terminal_result(content, AttachmentProcessingState.FAILED, ExtractionReason.CONTENT_TYPE_MISMATCH)
    if is_pdf_signal:
        try:
            extraction = extract_pdf(
                content,
                filename=filename,
                mime_type=mime_type,
                max_pages=settings.pdf_max_pages,
                max_characters=settings.extraction_max_characters,
            )
        except PDFExtractionError as error:
            return _terminal_result(
                content,
                AttachmentProcessingState.FAILED,
                ExtractionReason(error.reason.value),
                ExtractionMethod.PYMUPDF,
            )
        return classify_pdf_extraction(extraction)
    if is_docx_signal:
        return extract_docx(
            content,
            filename=filename,
            mime_type=mime_type,
            max_paragraphs=settings.docx_max_paragraphs,
            max_tables=settings.docx_max_tables,
            max_table_cells=settings.docx_max_table_cells,
            max_characters=settings.extraction_max_characters,
        )
    return _terminal_result(
        content,
        AttachmentProcessingState.UNSUPPORTED,
        ExtractionReason.UNSUPPORTED_MEDIA_TYPE,
    )


def _terminal_result(
    content: HashedAttachmentContent,
    status: AttachmentProcessingState,
    reason: ExtractionReason,
    method: ExtractionMethod | None = None,
) -> AttachmentExtractionResult:
    return AttachmentExtractionResult(
        attachment_id=content.attachment_id,
        content_hash=content.content_hash,
        status=status,
        extraction_method=method,
        extracted_text=None,
        reason=reason,
        source_size_bytes=content.size_bytes,
        processed_unit_count=0,
    )
