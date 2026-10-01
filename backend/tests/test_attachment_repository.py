from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.enums import AttachmentProcessingState
from app.repositories.attachment import AttachmentRepository


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
