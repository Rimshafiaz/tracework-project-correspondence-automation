from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts.attachment_content import AttachmentContent
from app.core.config import Settings
from app.models.enums import AttachmentProcessingState
from app.services.gmail_attachment_preparation import GmailAttachmentPreparationService


def _settings():
    return Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        _env_file=None,
    )


def test_pending_gmail_attachments_are_downloaded_and_extracted_once():
    event = SimpleNamespace(id=uuid4(), source="gmail", external_event_id="message-1")
    pending = SimpleNamespace(
        id=uuid4(),
        source_attachment_id="api:provider-1",
        size_bytes=4,
        processing_state=AttachmentProcessingState.PENDING,
    )
    complete = SimpleNamespace(
        id=uuid4(),
        source_attachment_id="api:provider-2",
        size_bytes=4,
        processing_state=AttachmentProcessingState.EXTRACTED,
    )
    correspondence = MagicMock()
    correspondence.get.return_value = event
    attachments = MagicMock()
    attachments.list_for_correspondence_event.return_value = (pending, complete)
    service = GmailAttachmentPreparationService(
        gmail_service=MagicMock(),
        settings=_settings(),
        correspondence_repository=correspondence,
        attachment_repository=attachments,
    )
    content = AttachmentContent(
        attachment_id=pending.id,
        content=b"data",
        size_bytes=4,
    )
    service.extraction_service.process = MagicMock(
        return_value=SimpleNamespace(processed=True)
    )

    with patch(
        "app.services.gmail_attachment_preparation.download_gmail_attachment",
        return_value=content,
    ) as download:
        result = service.process(event.id)

    assert result.processed_attachment_ids == (pending.id,)
    download.assert_called_once()
    service.extraction_service.process.assert_called_once_with(pending, content)


def test_non_gmail_event_does_not_use_the_gmail_provider():
    event = SimpleNamespace(id=uuid4(), source="fixture", external_event_id="fixture-1")
    correspondence = MagicMock()
    correspondence.get.return_value = event
    attachments = MagicMock()
    service = GmailAttachmentPreparationService(
        gmail_service=MagicMock(),
        settings=_settings(),
        correspondence_repository=correspondence,
        attachment_repository=attachments,
    )

    result = service.process(event.id)

    assert result.processed_attachment_ids == ()
    attachments.list_for_correspondence_event.assert_not_called()
