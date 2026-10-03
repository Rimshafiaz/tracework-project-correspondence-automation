from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState
from app.contracts.attachment_extraction import AttachmentExtractionMetadata, AttachmentExtractionResult, ExtractionBounds, ExtractionMethod
from app.repositories.attachment import (
    AttachmentContentHashConflict,
    AttachmentExtractionMismatch,
    AttachmentRepository,
)


def _bounds() -> ExtractionBounds:
    return ExtractionBounds(
        attachment_max_size_bytes=100,
        pdf_max_pages=10,
        extraction_max_characters=1_000,
        docx_max_paragraphs=100,
        docx_max_tables=10,
        docx_max_table_cells=100,
    )


def test_create_adds_pending_attachment_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = AttachmentRepository(session)
    event_id = uuid4()

    attachment = repository.create(
        correspondence_event_id=event_id,
        source_attachment_id="attachment-1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=321,
    )

    assert attachment.correspondence_event_id == event_id
    assert attachment.processing_state is AttachmentProcessingState.PENDING
    session.add.assert_called_once_with(attachment)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_list_for_correspondence_event_is_scoped_and_ordered() -> None:
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = []

    AttachmentRepository(session).list_for_correspondence_event(uuid4())

    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1
    assert len(statement._order_by_clauses) == 2


def test_set_content_hash_is_idempotent_and_does_not_commit() -> None:
    session = MagicMock(spec=Session)
    repository = AttachmentRepository(session)
    attachment = Attachment(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        source_attachment_id="api:attachment-1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=3,
        processing_state=AttachmentProcessingState.PENDING,
    )
    digest = "a" * 64

    repository.set_content_hash(attachment, content_hash=digest)
    repository.set_content_hash(attachment, content_hash=digest)

    assert attachment.content_hash == digest
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_set_content_hash_rejects_conflicting_content() -> None:
    session = MagicMock(spec=Session)
    repository = AttachmentRepository(session)
    attachment = Attachment(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        source_attachment_id="api:attachment-1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=3,
        content_hash="a" * 64,
        processing_state=AttachmentProcessingState.PENDING,
    )

    with pytest.raises(AttachmentContentHashConflict, match="different content hash"):
        repository.set_content_hash(attachment, content_hash="b" * 64)

    assert attachment.content_hash == "a" * 64
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_save_extraction_result_persists_typed_metadata_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = AttachmentRepository(session)
    attachment = Attachment(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        source_attachment_id="api:1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=3,
        processing_state=AttachmentProcessingState.PENDING,
    )
    result = AttachmentExtractionResult(
        attachment_id=attachment.id,
        content_hash="a" * 64,
        status=AttachmentProcessingState.FAILED,
        extraction_method=ExtractionMethod.PYMUPDF,
        extracted_text=None,
        reason="EMPTY_PDF",
        source_size_bytes=3,
        processed_unit_count=1,
    )
    metadata = AttachmentExtractionMetadata(
        extraction_method=result.extraction_method,
        reason=result.reason,
        truncated=False,
        processed_unit_count=1,
        bounds=_bounds(),
    )

    repository.save_extraction_result(attachment, result=result, metadata=metadata)

    assert attachment.content_hash == "a" * 64
    assert attachment.processing_state is AttachmentProcessingState.FAILED
    assert attachment.extraction_metadata["schema_version"] == 1
    assert attachment.extraction_metadata["bounds"]["pdf_max_pages"] == 10
    assert session.flush.call_count == 2
    session.commit.assert_not_called()


def test_save_extraction_result_is_idempotent_and_rejects_wrong_attachment() -> None:
    session = MagicMock(spec=Session)
    repository = AttachmentRepository(session)
    attachment = Attachment(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        source_attachment_id="api:1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=3,
        content_hash="a" * 64,
        processing_state=AttachmentProcessingState.FAILED,
    )
    result = AttachmentExtractionResult(
        attachment_id=attachment.id,
        content_hash="a" * 64,
        status=AttachmentProcessingState.FAILED,
        extraction_method=ExtractionMethod.PYMUPDF,
        extracted_text=None,
        reason="EMPTY_PDF",
        source_size_bytes=3,
        processed_unit_count=1,
    )
    metadata = AttachmentExtractionMetadata(
        extraction_method=result.extraction_method,
        reason=result.reason,
        truncated=False,
        processed_unit_count=1,
        bounds=_bounds(),
    )
    attachment.extraction_metadata = metadata.model_dump(mode="json")

    repository.save_extraction_result(attachment, result=result, metadata=metadata)
    wrong_result = result.model_copy(update={"attachment_id": uuid4()})
    with pytest.raises(AttachmentExtractionMismatch):
        repository.save_extraction_result(attachment, result=wrong_result, metadata=metadata)

    session.flush.assert_not_called()
