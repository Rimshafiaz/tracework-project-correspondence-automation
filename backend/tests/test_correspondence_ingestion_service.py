from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.adapters.gmail.normalizer import GmailAttachment, GmailMessage, normalize_gmail_message
from app.models.correspondence_event import CorrespondenceEvent
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.services.correspondence_ingestion import CorrespondenceIngestionService


def gmail_message() -> GmailMessage:
    return GmailMessage(
        message_id="message-1",
        thread_id="thread-1",
        sender_header="Sender <SENDER@example.com>",
        subject="Status update",
        body="Attached report",
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
        attachments=(
            GmailAttachment(
                attachment_id="attachment-1",
                filename="report.pdf",
                mime_type="application/pdf",
                size_bytes=321,
            ),
        ),
    )


def test_ingest_persists_normalized_event_and_attachment_metadata() -> None:
    event_repository = MagicMock(spec=CorrespondenceEventRepository)
    attachment_repository = MagicMock(spec=AttachmentRepository)
    session = MagicMock(spec=Session)
    event_repository.session = session
    attachment_repository.session = session
    event_repository.get_by_external_identity.return_value = None
    stored_event = MagicMock(spec=CorrespondenceEvent, id=uuid4())
    event_repository.create.return_value = stored_event
    service = CorrespondenceIngestionService(event_repository, attachment_repository)

    result = service.ingest(normalize_gmail_message(gmail_message()))

    assert result.event is stored_event
    assert result.created is True
    event_repository.create.assert_called_once_with(
        source="gmail",
        external_event_id="message-1",
        external_conversation_id="thread-1",
        sender_identifier="sender@example.com",
        sender_email="sender@example.com",
        sender_name="Sender",
        subject="Status update",
        body="Attached report",
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
        source_metadata=None,
    )
    attachment_repository.create.assert_called_once_with(
        correspondence_event_id=stored_event.id,
        source_attachment_id="attachment-1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=321,
    )


def test_ingest_returns_existing_event_without_duplicate_writes() -> None:
    event_repository = MagicMock(spec=CorrespondenceEventRepository)
    attachment_repository = MagicMock(spec=AttachmentRepository)
    session = MagicMock(spec=Session)
    event_repository.session = session
    attachment_repository.session = session
    existing = MagicMock(spec=CorrespondenceEvent)
    event_repository.get_by_external_identity.return_value = existing
    service = CorrespondenceIngestionService(event_repository, attachment_repository)

    first_retry = service.ingest(normalize_gmail_message(gmail_message()))
    second_retry = service.ingest(normalize_gmail_message(gmail_message()))

    assert first_retry.event is existing
    assert second_retry.event is existing
    assert first_retry.created is False
    assert second_retry.created is False
    event_repository.create.assert_not_called()
    attachment_repository.create.assert_not_called()


def test_ingest_requires_one_shared_database_session() -> None:
    event_repository = MagicMock(spec=CorrespondenceEventRepository)
    attachment_repository = MagicMock(spec=AttachmentRepository)
    event_repository.session = MagicMock(spec=Session)
    attachment_repository.session = MagicMock(spec=Session)

    with pytest.raises(ValueError, match="share one database session"):
        CorrespondenceIngestionService(event_repository, attachment_repository)
