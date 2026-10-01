from unittest.mock import MagicMock
from uuid import uuid4

import pymupdf
import pytest
from sqlalchemy.orm import Session

from app.contracts.attachment_content import AttachmentContent
from app.core.config import Settings
from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState
from app.repositories.attachment import AttachmentExtractionMismatch, AttachmentRepository
from app.services.attachment_extraction import AttachmentExtractionService
from app.services.attachment_hashing import hash_attachment_content
from app.services.pdf_fallback import build_pdf_fallback_request


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=False,
    )


def _attachment(*, filename: str = "evidence.pdf", mime_type: str = "application/pdf") -> Attachment:
    return Attachment(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        source_attachment_id="api:attachment-1",
        filename=filename,
        mime_type=mime_type,
        size_bytes=0,
        processing_state=AttachmentProcessingState.PENDING,
    )


def _pdf(*, text: str | None = None, image: bool = False) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    if image:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1, 1), False)
        pixmap.clear_with(255)
        page.insert_image(pymupdf.Rect(0, 0, 10, 10), pixmap=pixmap)
    data = document.tobytes()
    document.close()
    return data


def _content(attachment: Attachment, data: bytes) -> AttachmentContent:
    attachment.size_bytes = len(data)
    return AttachmentContent(
        attachment_id=attachment.id,
        content=data,
        size_bytes=len(data),
    )


def test_processes_and_persists_downloaded_content_without_committing() -> None:
    session = MagicMock(spec=Session)
    attachment = _attachment()
    content = _content(attachment, _pdf(text="Traceable evidence"))
    service = AttachmentExtractionService(AttachmentRepository(session), _settings())

    outcome = service.process(attachment, content)

    assert outcome.processed is True
    assert outcome.result is not None
    assert attachment.processing_state is AttachmentProcessingState.EXTRACTED
    assert attachment.extracted_text == "Traceable evidence"
    assert attachment.content_hash is not None
    assert attachment.extraction_metadata["schema_version"] == 1
    assert attachment.extraction_metadata["pdf_segments"][0]["page_number"] == 1
    session.commit.assert_not_called()


def test_terminal_retry_is_an_idempotent_noop() -> None:
    session = MagicMock(spec=Session)
    attachment = _attachment()
    content = _content(attachment, _pdf(text="Evidence"))
    service = AttachmentExtractionService(AttachmentRepository(session), _settings())
    service.process(attachment, content)
    flush_count = session.flush.call_count

    retry = service.process(attachment, content)

    assert retry.processed is False
    assert retry.result is None
    assert session.flush.call_count == flush_count
    session.commit.assert_not_called()


def test_image_pdf_is_persisted_for_fallback_without_calling_ai() -> None:
    session = MagicMock(spec=Session)
    attachment = _attachment()
    content = _content(attachment, _pdf(image=True))
    service = AttachmentExtractionService(AttachmentRepository(session), _settings())

    outcome = service.process(attachment, content)

    assert outcome.result is not None
    assert attachment.processing_state is AttachmentProcessingState.FALLBACK_REQUIRED
    assert attachment.extraction_metadata["reason"] == "PDF_IMAGE_ONLY"
    request = build_pdf_fallback_request(attachment, hash_attachment_content(content))
    assert request.content == content.content


def test_unsupported_format_is_persisted_visibly() -> None:
    session = MagicMock(spec=Session)
    attachment = _attachment(filename="photo.png", mime_type="image/png")
    content = _content(attachment, b"image bytes")
    service = AttachmentExtractionService(AttachmentRepository(session), _settings())

    service.process(attachment, content)

    assert attachment.processing_state is AttachmentProcessingState.UNSUPPORTED
    assert attachment.extraction_metadata["reason"] == "UNSUPPORTED_MEDIA_TYPE"


def test_rejects_content_for_a_different_attachment_or_size() -> None:
    session = MagicMock(spec=Session)
    attachment = _attachment()
    content = AttachmentContent(attachment_id=uuid4(), content=b"x", size_bytes=1)
    service = AttachmentExtractionService(AttachmentRepository(session), _settings())

    with pytest.raises(AttachmentExtractionMismatch):
        service.process(attachment, content)

    session.flush.assert_not_called()
