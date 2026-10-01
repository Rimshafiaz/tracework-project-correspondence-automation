from app.contracts.attachment_extraction import AttachmentExtractionResult, ExtractionMethod, ExtractionReason, PDFTextSegment
from app.contracts.pdf_extraction import PDFExtraction
from app.models.enums import AttachmentProcessingState


def classify_pdf_extraction(extraction: PDFExtraction) -> AttachmentExtractionResult:
    meaningful_pages = {
        page.page_number for page in extraction.pages if any(character.isalnum() for character in page.text)
    }
    image_pages = {page.page_number for page in extraction.pages if page.has_embedded_images}
    image_without_text = image_pages - meaningful_pages

    text = extraction.extracted_text or None
    segments = tuple(
        PDFTextSegment(
            page_number=page.page_number,
            text_start=page.text_start,
            text_end=page.text_end,
            text=page.text,
        )
        for page in extraction.pages
        if page.text
    )

    if not meaningful_pages and image_pages:
        status = AttachmentProcessingState.FALLBACK_REQUIRED
        reason = ExtractionReason.PDF_IMAGE_ONLY
    elif meaningful_pages and image_without_text:
        status = AttachmentProcessingState.FALLBACK_REQUIRED
        reason = ExtractionReason.PDF_PARTIAL_IMAGE_TEXT
    elif not meaningful_pages:
        status = AttachmentProcessingState.FAILED
        reason = ExtractionReason.EMPTY_PDF
        text = None
        segments = ()
    else:
        status = AttachmentProcessingState.EXTRACTED
        reason = ExtractionReason.EXTRACTION_LIMIT_REACHED if extraction.truncated else None

    return AttachmentExtractionResult(
        attachment_id=extraction.attachment_id,
        content_hash=extraction.content_hash,
        status=status,
        extraction_method=ExtractionMethod.PYMUPDF,
        extracted_text=text,
        pdf_segments=segments,
        reason=reason,
        truncated=extraction.truncated,
        source_size_bytes=extraction.source_size_bytes,
        processed_unit_count=extraction.processed_page_count,
    )
