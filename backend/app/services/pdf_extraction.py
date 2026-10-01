from enum import StrEnum

import pymupdf

from app.contracts.attachment_content import HashedAttachmentContent
from app.contracts.pdf_extraction import PDFExtraction, PDFPageExtraction


class PDFExtractionFailure(StrEnum):
    CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"
    MALFORMED_PDF = "MALFORMED_PDF"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"


class PDFExtractionError(ValueError):
    def __init__(self, reason: PDFExtractionFailure) -> None:
        self.reason = reason
        super().__init__(reason.value)


def extract_pdf(
    content: HashedAttachmentContent,
    *,
    filename: str,
    mime_type: str,
    max_pages: int,
    max_characters: int,
) -> PDFExtraction:
    if not filename.casefold().endswith(".pdf") or mime_type.casefold() != "application/pdf":
        raise PDFExtractionError(PDFExtractionFailure.CONTENT_TYPE_MISMATCH)
    if max_pages <= 0 or max_characters <= 0:
        raise ValueError("PDF extraction limits must be positive")
    if b"%PDF-" not in content.content[:1024]:
        raise PDFExtractionError(PDFExtractionFailure.MALFORMED_PDF)

    try:
        document = pymupdf.open(stream=content.content, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
        raise PDFExtractionError(PDFExtractionFailure.MALFORMED_PDF) from error

    with document:
        if document.needs_pass:
            raise PDFExtractionError(PDFExtractionFailure.ENCRYPTED_PDF)

        total_page_count = document.page_count
        parts: list[str] = []
        pages: list[PDFPageExtraction] = []
        text_length = 0
        truncated = total_page_count > max_pages

        for page_index in range(min(total_page_count, max_pages)):
            page = document[page_index]
            page_text = page.get_text("text").replace("\r\n", "\n").replace("\r", "\n").strip()
            separator = "\n\n" if page_text and text_length else ""
            remaining = max_characters - text_length
            if len(separator) + len(page_text) > remaining:
                truncated = True
                page_text = page_text[: max(0, remaining - len(separator))]
                separator = separator if page_text else ""

            parts.append(separator + page_text)
            start = text_length + len(separator)
            text_length += len(separator) + len(page_text)
            pages.append(
                PDFPageExtraction(
                    page_number=page_index + 1,
                    text_start=start,
                    text_end=text_length,
                    text=page_text,
                    has_embedded_images=bool(page.get_images(full=True)),
                )
            )
            if text_length == max_characters:
                truncated = truncated or page_index + 1 < total_page_count
                break

    return PDFExtraction(
        attachment_id=content.attachment_id,
        content_hash=content.content_hash,
        source_size_bytes=content.size_bytes,
        extracted_text="".join(parts),
        pages=tuple(pages),
        total_page_count=total_page_count,
        processed_page_count=len(pages),
        truncated=truncated,
    )
