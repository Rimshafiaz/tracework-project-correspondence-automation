from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.enums import DocumentFilingStatus


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: UUID) -> Document | None:
        return self.session.get(Document, document_id)

    def get_for_update(self, document_id: UUID) -> Document | None:
        return self.session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )

    def get_by_project_attachment(
        self,
        *,
        project_id: UUID,
        source_attachment_id: UUID,
        for_update: bool = False,
    ) -> Document | None:
        statement = select(Document).where(
            Document.project_id == project_id,
            Document.source_attachment_id == source_attachment_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def create_pending(
        self,
        *,
        project_id: UUID,
        source_attachment_id: UUID,
        filename: str,
        category: str,
        content_hash: str,
    ) -> Document:
        document = Document(
            project_id=project_id,
            source_attachment_id=source_attachment_id,
            filename=filename,
            category=category,
            content_hash=content_hash,
            filing_status=DocumentFilingStatus.PENDING,
        )
        self.session.add(document)
        self.session.flush()
        return document

    def mark_filed(
        self,
        document: Document,
        *,
        drive_file_id: str,
        drive_parent_folder_id: str,
        filed_at: datetime,
    ) -> Document:
        document.filing_status = DocumentFilingStatus.FILED
        document.drive_file_id = drive_file_id
        document.drive_parent_folder_id = drive_parent_folder_id
        document.failure_code = None
        document.filed_at = filed_at
        self.session.flush()
        return document

    def mark_retryable_failure(
        self,
        document: Document,
        *,
        failure_code: str,
    ) -> Document:
        document.filing_status = DocumentFilingStatus.RETRYABLE_FAILURE
        document.drive_file_id = None
        document.drive_parent_folder_id = None
        document.failure_code = failure_code
        document.filed_at = None
        self.session.flush()
        return document
