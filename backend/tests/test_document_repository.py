from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.enums import DocumentFilingStatus
from app.repositories.document import DocumentRepository


def test_document_repository_tracks_pending_failure_and_success_without_new_rows():
    session = MagicMock()
    repository = DocumentRepository(session)
    document = repository.create_pending(
        project_id=uuid4(),
        source_attachment_id=uuid4(),
        filename="report.pdf",
        category="Documents",
        content_hash="a" * 64,
    )

    assert document.filing_status is DocumentFilingStatus.PENDING
    assert document.drive_file_id is None
    assert session.add.call_count == 1

    repository.mark_retryable_failure(document, failure_code="DRIVE_UNAVAILABLE")
    assert document.filing_status is DocumentFilingStatus.RETRYABLE_FAILURE
    assert document.failure_code == "DRIVE_UNAVAILABLE"

    filed_at = datetime.now(UTC)
    repository.mark_filed(
        document,
        drive_file_id="drive-file-1",
        drive_parent_folder_id="folder-1",
        filed_at=filed_at,
    )
    assert document.filing_status is DocumentFilingStatus.FILED
    assert document.drive_file_id == "drive-file-1"
    assert document.filed_at == filed_at
    assert session.add.call_count == 1
