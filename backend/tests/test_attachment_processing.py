from io import BytesIO
from uuid import uuid4

import pymupdf
from docx import Document

from app.contracts.attachment_content import AttachmentContent
from app.contracts.attachment_extraction import ExtractionReason
from app.core.config import Settings
from app.models.enums import AttachmentProcessingState
from app.services.attachment_hashing import hash_attachment_content
from app.services.attachment_processing import process_attachment
from app.services.docx_extraction import DOCX_MIME_TYPE


def _settings(**overrides: int) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=False,
        **overrides,
    )


def _content(data: bytes):
    return hash_attachment_content(
        AttachmentContent(attachment_id=uuid4(), content=data, size_bytes=len(data))
    )


def _pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _docx(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_routes_pdf_through_extraction_and_quality_classification() -> None:
    result = process_attachment(
        _content(_pdf("PDF evidence")),
        filename="evidence.pdf",
        mime_type="application/pdf",
        settings=_settings(),
    )

    assert result.status is AttachmentProcessingState.EXTRACTED
    assert result.extracted_text == "PDF evidence"
    assert result.pdf_segments


def test_routes_docx_through_docx_extraction() -> None:
    result = process_attachment(
        _content(_docx("DOCX evidence")),
        filename="evidence.docx",
        mime_type=DOCX_MIME_TYPE,
        settings=_settings(),
    )

    assert result.status is AttachmentProcessingState.EXTRACTED
    assert result.extracted_text == "DOCX evidence"
    assert result.docx_segments


def test_rejects_empty_and_oversized_content_before_format_routing() -> None:
    empty = process_attachment(
        _content(b""), filename="empty.pdf", mime_type="application/pdf", settings=_settings()
    )
    oversized = process_attachment(
        _content(b"12"),
        filename="file.txt",
        mime_type="text/plain",
        settings=_settings(attachment_max_size_bytes=1),
    )

    assert empty.reason is ExtractionReason.EMPTY_ATTACHMENT
    assert oversized.reason is ExtractionReason.ATTACHMENT_TOO_LARGE


def test_returns_unsupported_for_unapproved_formats() -> None:
    result = process_attachment(
        _content(b"image"),
        filename="photo.png",
        mime_type="image/png",
        settings=_settings(),
    )

    assert result.status is AttachmentProcessingState.UNSUPPORTED
    assert result.reason is ExtractionReason.UNSUPPORTED_MEDIA_TYPE


def test_recognized_format_mismatches_and_pdf_failures_are_typed() -> None:
    mismatch = process_attachment(
        _content(_pdf("text")),
        filename="file.pdf",
        mime_type=DOCX_MIME_TYPE,
        settings=_settings(),
    )
    malformed = process_attachment(
        _content(b"%PDF-not-valid"),
        filename="file.pdf",
        mime_type="application/pdf",
        settings=_settings(),
    )

    assert mismatch.reason is ExtractionReason.CONTENT_TYPE_MISMATCH
    assert malformed.reason is ExtractionReason.MALFORMED_PDF
