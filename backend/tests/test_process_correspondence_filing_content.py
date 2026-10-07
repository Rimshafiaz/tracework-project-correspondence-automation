import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.commands import process_correspondence as command
from app.contracts.attachment_content import AttachmentContent
from app.contracts.document_filing import DocumentFilingAuthorization, DocumentFilingOutcomeStatus, DriveFileRecord
from app.core.config import Settings
from app.models.enums import AttachmentProcessingState, DocumentFilingStatus, TransitionStatus
from app.services.attachment_extraction import AttachmentExtractionService
from app.services.document_filing import DocumentFilingService


@pytest.mark.parametrize("processing_state", [AttachmentProcessingState.EXTRACTED, AttachmentProcessingState.PENDING])
def test_normal_gmail_filing_loader_passes_bytes_to_hashing(monkeypatch, processing_state):
    content = b"document bytes"
    event = SimpleNamespace(id=uuid4(), source="gmail", external_event_id="message-id")
    attachment = SimpleNamespace(
        id=uuid4(), source_attachment_id="api:attachment-id",
        size_bytes=len(content), processing_state=processing_state,
        filename="report.pdf", mime_type="application/pdf",
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    downloaded = AttachmentContent(
        attachment_id=attachment.id, content=content, size_bytes=len(content),
    )
    session = MagicMock()
    repositories = {}
    for name in (
        "CorrespondenceEventRepository", "AttachmentRepository", "ProjectRepository",
        "ProjectIdentifierRepository", "ProjectContactRepository",
        "CorrespondenceProjectLinkRepository", "RequirementRepository",
        "LineageRepository", "ReviewItemRepository", "DocumentRepository",
    ):
        repository = MagicMock()
        repositories[name] = repository
        monkeypatch.setattr(command, name, MagicMock(return_value=repository))
    repositories["CorrespondenceEventRepository"].get.return_value = event
    repositories["AttachmentRepository"].list_for_correspondence_event.return_value = (attachment,)
    documents = repositories["DocumentRepository"]
    lineage = repositories["LineageRepository"]
    project_id = uuid4()
    evaluation = SimpleNamespace(id=uuid4())
    document = SimpleNamespace(id=uuid4(), filing_status=DocumentFilingStatus.PENDING)
    transition = SimpleNamespace(id=uuid4(), status=TransitionStatus.PREVIEWED)
    documents.get_by_project_attachment.return_value = None
    documents.create_pending.return_value = document
    documents.get_for_update.return_value = document
    lineage.get_state_transition_for_update.side_effect = [None, transition]
    lineage.create_transition.return_value = transition
    lineage.list_policy_evidence.return_value = ()
    lineage.get_audit_event_for_transition.return_value = SimpleNamespace(id=uuid4())
    drive = MagicMock()
    drive.ensure_folder.return_value = "folder"
    drive.find_file.return_value = None
    drive.upload_file.return_value = DriveFileRecord(
        file_id="file", name=attachment.filename, parent_folder_id="folder",
    )
    repositories["ProjectRepository"].get.return_value = SimpleNamespace(
        id=project_id, project_code="TW-001", name="Project",
    )
    monkeypatch.setattr(command, "SessionLocal", lambda: session)
    monkeypatch.setattr(command, "create_drive_client", lambda _settings: drive)
    monkeypatch.setattr(command, "create_gmail_client", lambda _settings: MagicMock())
    monkeypatch.setattr(command, "download_gmail_attachment", MagicMock(return_value=downloaded))
    monkeypatch.setattr(command, "build_project_resolver_agent", lambda _settings: MagicMock())
    monkeypatch.setattr(command, "build_requirement_reconciler_agent", lambda _settings: MagicMock())
    monkeypatch.setattr(command, "DocumentRevisionService", lambda **_kwargs: MagicMock())
    monkeypatch.setattr(
        "app.services.gmail_attachment_preparation.download_gmail_attachment",
        MagicMock(return_value=downloaded),
    )
    extraction = MagicMock(return_value=SimpleNamespace(processed=True))
    monkeypatch.setattr(AttachmentExtractionService, "process", extraction)
    real_sha256 = hashlib.sha256
    hashed_values = []

    def hash_bytes(value):
        assert isinstance(value, bytes)
        assert not isinstance(value, AttachmentContent)
        hashed_values.append(value)
        return real_sha256(value)

    monkeypatch.setattr("app.services.document_filing.hashlib.sha256", hash_bytes)

    class Workflow:
        def __init__(self, **kwargs):
            self.filing = kwargs["document_filing_service"]

        async def process(self, event_id):
            assert event_id == event.id
            assert isinstance(self.filing, DocumentFilingService)
            return self.filing._file_one(
                event=event, attachment=attachment, project_id=project_id,
                proposal_id=uuid4(), evaluation=evaluation,
                authorization=DocumentFilingAuthorization.AUTOMATIC_PROJECT_POLICY,
            )

    monkeypatch.setattr(command, "CoreCorrespondenceWorkflowService", Workflow)
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=True, drive_enabled=True,
        gmail_account_email="operator@example.test", gmail_label_id="label-id",
        gmail_initial_after_epoch_seconds=1, _env_file=None,
    )

    result = asyncio.run(command.process_correspondence_event(event.id, settings))

    assert result.status is DocumentFilingOutcomeStatus.FILED
    assert hashed_values == [content]
    assert drive.upload_file.call_args.kwargs["content"] == content
    if processing_state is AttachmentProcessingState.PENDING:
        extraction.assert_called_once_with(attachment, downloaded)
    else:
        extraction.assert_not_called()
    session.close.assert_called_once()
