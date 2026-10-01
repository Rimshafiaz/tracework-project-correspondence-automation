from uuid import uuid4

import pytest

from app.contracts.attachment_extraction import ExtractionMethod, ExtractionReason
from app.contracts.pdf_extraction import PDFExtraction, PDFPageExtraction
from app.models.enums import AttachmentProcessingState
from app.services.pdf_quality import classify_pdf_extraction


def _extraction(*pages: tuple[str, bool], truncated: bool = False) -> PDFExtraction:
    text_parts: list[str] = []
    page_results: list[PDFPageExtraction] = []
    text_length = 0
    for page_number, (text, has_images) in enumerate(pages, start=1):
        separator = "\n\n" if text and text_length else ""
        text_parts.append(separator + text)
        start = text_length + len(separator)
        text_length += len(separator) + len(text)
        page_results.append(
            PDFPageExtraction(
                page_number=page_number,
                text_start=start,
                text_end=text_length,
                text=text,
                has_embedded_images=has_images,
            )
        )
    return PDFExtraction(
        attachment_id=uuid4(),
        content_hash="a" * 64,
        source_size_bytes=123,
        extracted_text="".join(text_parts),
        pages=tuple(page_results),
        total_page_count=len(pages),
        processed_page_count=len(pages),
        truncated=truncated,
    )


def test_meaningful_unicode_text_is_extracted_with_provenance() -> None:
    extraction = _extraction(("Project 42", False), ("\u9879\u76ee", True))

    result = classify_pdf_extraction(extraction)

    assert result.status is AttachmentProcessingState.EXTRACTED
    assert result.extraction_method is ExtractionMethod.PYMUPDF
    assert result.reason is None
    assert result.extracted_text == extraction.extracted_text
    assert [segment.page_number for segment in result.pdf_segments] == [1, 2]
    assert result.source_size_bytes == 123


def test_image_only_pdf_requires_fallback() -> None:
    result = classify_pdf_extraction(_extraction(("", True), ("---", False)))

    assert result.status is AttachmentProcessingState.FALLBACK_REQUIRED
    assert result.reason is ExtractionReason.PDF_IMAGE_ONLY


def test_mixed_text_and_image_only_pages_require_fallback() -> None:
    result = classify_pdf_extraction(_extraction(("Useful text", False), ("", True)))

    assert result.status is AttachmentProcessingState.FALLBACK_REQUIRED
    assert result.reason is ExtractionReason.PDF_PARTIAL_IMAGE_TEXT
    assert result.extracted_text == "Useful text"


@pytest.mark.parametrize("pages", [(), (("", False),), (("!?", False),)])
def test_pdf_without_meaningful_text_or_images_is_empty(pages: tuple[tuple[str, bool], ...]) -> None:
    result = classify_pdf_extraction(_extraction(*pages))

    assert result.status is AttachmentProcessingState.FAILED
    assert result.reason is ExtractionReason.EMPTY_PDF
    assert result.extracted_text is None
    assert result.pdf_segments == ()


def test_truncated_text_extraction_records_limit_reason() -> None:
    result = classify_pdf_extraction(_extraction(("bounded text", False), truncated=True))

    assert result.status is AttachmentProcessingState.EXTRACTED
    assert result.reason is ExtractionReason.EXTRACTION_LIMIT_REACHED
    assert result.truncated is True
