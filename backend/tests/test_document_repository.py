from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.enums import DocumentFilingStatus, DocumentRevisionStatus
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
    assert document.revision_status is DocumentRevisionStatus.UNASSESSED
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


def test_document_repository_reads_family_members_in_deterministic_order():
    session = MagicMock()
    session.scalars.return_value = []
    repository = DocumentRepository(session)

    assert repository.list_family_members(
        project_id=uuid4(),
        category="Documents",
        document_family_key="structural plan",
        for_update=True,
    ) == ()

    statement = session.scalars.call_args.args[0]
    rendered = str(statement)
    assert "documents.project_id" in rendered
    assert "documents.category" in rendered
    assert "documents.document_family_key" in rendered
    assert "ORDER BY documents.created_at, documents.id" in rendered
    assert statement._for_update_arg is not None


def test_document_repository_fetches_current_family_member():
    session = MagicMock()
    repository = DocumentRepository(session)

    repository.get_current_family_member(
        project_id=uuid4(),
        category="Documents",
        document_family_key="structural plan",
        for_update=True,
    )

    statement = session.scalar.call_args.args[0]
    assert "documents.revision_status" in str(statement)
    assert statement._for_update_arg is not None


def test_document_repository_updates_revision_metadata_on_existing_document():
    session = MagicMock()
    repository = DocumentRepository(session)
    document = repository.create_pending(
        project_id=uuid4(),
        source_attachment_id=uuid4(),
        filename="Structural Plan Rev 4.pdf",
        category="Documents",
        content_hash="a" * 64,
    )
    decided_at = datetime.now(UTC)

    result = repository.update_revision_metadata(
        document,
        document_family_key="structural plan",
        revision_label="Rev 4",
        revision_normalized="REV-4",
        revision_order=4,
        revision_status=DocumentRevisionStatus.CURRENT,
        revision_decided_at=decided_at,
    )

    assert result is document
    assert document.document_family_key == "structural plan"
    assert document.revision_label == "Rev 4"
    assert document.revision_normalized == "REV-4"
    assert document.revision_order == 4
    assert document.revision_status is DocumentRevisionStatus.CURRENT
    assert document.revision_decided_at == decided_at
    assert session.add.call_count == 1
