from dataclasses import dataclass
from uuid import UUID

from app.adapters.gmail.attachment_content import download_gmail_attachment
from app.core.config import Settings
from app.models.enums import AttachmentProcessingState
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.services.attachment_extraction import AttachmentExtractionService


@dataclass(frozen=True)
class GmailAttachmentPreparationResult:
    processed_attachment_ids: tuple[UUID, ...]


class GmailAttachmentPreparationService:
    """Downloads and extracts pending Gmail attachments before M7/M8 context use."""

    def __init__(
        self,
        *,
        gmail_service,
        settings: Settings,
        correspondence_repository: CorrespondenceEventRepository,
        attachment_repository: AttachmentRepository,
    ) -> None:
        self.gmail_service = gmail_service
        self.settings = settings
        self.correspondence_repository = correspondence_repository
        self.attachment_repository = attachment_repository
        self.extraction_service = AttachmentExtractionService(
            attachment_repository,
            settings,
        )

    def process(self, correspondence_event_id: UUID) -> GmailAttachmentPreparationResult:
        event = self.correspondence_repository.get(correspondence_event_id)
        if event is None:
            raise LookupError("correspondence event was not found")
        if event.source != "gmail":
            return GmailAttachmentPreparationResult(processed_attachment_ids=())

        processed = []
        for attachment in self.attachment_repository.list_for_correspondence_event(
            event.id
        ):
            if attachment.processing_state is not AttachmentProcessingState.PENDING:
                continue
            content = download_gmail_attachment(
                self.gmail_service,
                attachment_id=attachment.id,
                message_id=event.external_event_id,
                source_attachment_id=attachment.source_attachment_id,
                declared_size_bytes=attachment.size_bytes,
                max_size_bytes=self.settings.attachment_max_size_bytes,
            )
            outcome = self.extraction_service.process(attachment, content)
            if outcome.processed:
                processed.append(attachment.id)
        return GmailAttachmentPreparationResult(
            processed_attachment_ids=tuple(processed)
        )
