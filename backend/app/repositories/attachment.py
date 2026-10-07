from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.attachment_extraction import AttachmentExtractionMetadata, AttachmentExtractionResult
from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState


class AttachmentContentHashConflict(Exception):
    pass


class AttachmentExtractionMismatch(Exception):
    pass


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

    def list_for_correspondence_event(
        self,
        correspondence_event_id: UUID,
    ) -> Sequence[Attachment]:
        return self.session.scalars(
            select(Attachment)
            .where(Attachment.correspondence_event_id == correspondence_event_id)
            .order_by(Attachment.created_at, Attachment.id)
        ).all()

    def get_for_update(self, attachment_id: UUID) -> Attachment | None:
        return self.session.scalar(
            select(Attachment)
            .where(Attachment.id == attachment_id)
            .with_for_update()
        )

    def set_content_hash(
        self,
        attachment: Attachment,
        *,
        content_hash: str,
    ) -> Attachment:
        if attachment.content_hash is None:
            attachment.content_hash = content_hash
            self.session.flush()
            return attachment
        if attachment.content_hash != content_hash:
            raise AttachmentContentHashConflict(
                f"Attachment {attachment.id} already has a different content hash"
            )
        return attachment

    def save_extraction_result(
        self,
        attachment: Attachment,
        *,
        result: AttachmentExtractionResult,
        metadata: AttachmentExtractionMetadata,
    ) -> Attachment:
        if attachment.id != result.attachment_id or attachment.size_bytes != result.source_size_bytes:
            raise AttachmentExtractionMismatch("Extraction result does not match the attachment")
        if result.content_hash is not None:
            self.set_content_hash(attachment, content_hash=result.content_hash)

        metadata_json = metadata.model_dump(mode="json")
        unchanged = (
            attachment.extracted_text == result.extracted_text
            and attachment.extraction_metadata == metadata_json
            and attachment.processing_state is result.status
        )
        if unchanged:
            return attachment

        attachment.extracted_text = result.extracted_text
        attachment.extraction_metadata = metadata_json
        attachment.processing_state = result.status
        self.session.flush()
        return attachment
