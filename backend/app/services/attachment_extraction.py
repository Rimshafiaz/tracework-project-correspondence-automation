from dataclasses import dataclass

from app.contracts.attachment_content import AttachmentContent
from app.contracts.attachment_extraction import AttachmentExtractionMetadata, AttachmentExtractionResult, ExtractionBounds
from app.core.config import Settings
from app.models.attachment import Attachment
from app.models.enums import AttachmentProcessingState
from app.repositories.attachment import AttachmentExtractionMismatch, AttachmentRepository
from app.services.attachment_hashing import hash_attachment_content
from app.services.attachment_processing import process_attachment


@dataclass(frozen=True)
class AttachmentExtractionOutcome:
    attachment: Attachment
    processed: bool
    result: AttachmentExtractionResult | None


class AttachmentExtractionService:
    def __init__(self, repository: AttachmentRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def process(
        self,
        attachment: Attachment,
        content: AttachmentContent,
    ) -> AttachmentExtractionOutcome:
        if attachment.processing_state is not AttachmentProcessingState.PENDING:
            return AttachmentExtractionOutcome(attachment=attachment, processed=False, result=None)
        if attachment.id != content.attachment_id or attachment.size_bytes != content.size_bytes:
            raise AttachmentExtractionMismatch("Downloaded content does not match the attachment")

        hashed_content = hash_attachment_content(content)
        result = process_attachment(
            hashed_content,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            settings=self.settings,
        )
        metadata = AttachmentExtractionMetadata(
            extraction_method=result.extraction_method,
            reason=result.reason,
            truncated=result.truncated,
            processed_unit_count=result.processed_unit_count,
            bounds=ExtractionBounds(
                attachment_max_size_bytes=self.settings.attachment_max_size_bytes,
                pdf_max_pages=self.settings.pdf_max_pages,
                extraction_max_characters=self.settings.extraction_max_characters,
                docx_max_paragraphs=self.settings.docx_max_paragraphs,
                docx_max_tables=self.settings.docx_max_tables,
                docx_max_table_cells=self.settings.docx_max_table_cells,
            ),
            pdf_segments=result.pdf_segments,
            docx_segments=result.docx_segments,
        )
        self.repository.save_extraction_result(
            attachment,
            result=result,
            metadata=metadata,
        )
        return AttachmentExtractionOutcome(
            attachment=attachment,
            processed=True,
            result=result,
        )
