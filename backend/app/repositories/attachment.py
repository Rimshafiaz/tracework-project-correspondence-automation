from uuid import UUID

from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState


class AttachmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        correspondence_event_id: UUID,
        source_attachment_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
    ) -> Attachment:
        attachment = Attachment(
            correspondence_event_id=correspondence_event_id,
            source_attachment_id=source_attachment_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            processing_state=AttachmentProcessingState.PENDING,
        )
        self.session.add(attachment)
        self.session.flush()
        return attachment
