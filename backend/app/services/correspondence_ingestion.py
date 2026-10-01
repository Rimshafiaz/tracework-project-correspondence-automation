from dataclasses import dataclass

from app.contracts.correspondence import NormalizedCorrespondenceEvent
from app.models.correspondence_event import CorrespondenceEvent
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository


@dataclass(frozen=True)
class CorrespondenceIngestionResult:
    event: CorrespondenceEvent
    created: bool


class CorrespondenceIngestionService:
    def __init__(
        self,
        event_repository: CorrespondenceEventRepository,
        attachment_repository: AttachmentRepository,
    ) -> None:
        if event_repository.session is not attachment_repository.session:
            raise ValueError("ingestion repositories must share one database session")
        self.event_repository = event_repository
        self.attachment_repository = attachment_repository

    def ingest(
        self, correspondence: NormalizedCorrespondenceEvent
    ) -> CorrespondenceIngestionResult:
        existing = self.event_repository.get_by_external_identity(
            source=correspondence.source,
            external_event_id=correspondence.external_event_id,
        )
        if existing is not None:
            return CorrespondenceIngestionResult(event=existing, created=False)

        event = self.event_repository.create(
            source=correspondence.source,
            external_event_id=correspondence.external_event_id,
            external_conversation_id=correspondence.external_conversation_id,
            sender_identifier=correspondence.sender_identifier,
            sender_email=correspondence.sender_email,
            sender_name=correspondence.sender_name,
            subject=correspondence.subject,
            body=correspondence.body,
            received_at=correspondence.received_at,
            source_metadata=correspondence.source_metadata,
        )
        for attachment in correspondence.attachments:
            self.attachment_repository.create(
                correspondence_event_id=event.id,
                source_attachment_id=attachment.source_attachment_id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                size_bytes=attachment.size_bytes,
            )
        return CorrespondenceIngestionResult(event=event, created=True)
