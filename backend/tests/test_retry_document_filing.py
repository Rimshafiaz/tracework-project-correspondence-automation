from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.commands import retry_document_filing as command
from app.models.enums import CorrespondenceProcessingState, ProposalType
from app.services.policy.project_identity_rules import PROJECT_IDENTITY_POLICY_VERSION


def _command_dependencies(monkeypatch):
    session = MagicMock()
    lineage = MagicMock()
    proposal_id, evaluation_id = uuid4(), uuid4()
    event = SimpleNamespace(
        id=uuid4(), source="gmail", external_event_id="message-id",
        processing_state=CorrespondenceProcessingState.COMPLETED,
    )
    proposal = SimpleNamespace(
        id=proposal_id, proposal_type=ProposalType.PROJECT_RESOLUTION,
        correspondence_event=event,
    )
    evaluation = SimpleNamespace(
        id=evaluation_id, ai_proposal_id=proposal_id,
        policy_version=PROJECT_IDENTITY_POLICY_VERSION,
    )
    lineage.get_proposal.return_value = proposal
    lineage.get_policy_evaluation_by_id.return_value = evaluation
    service = MagicMock()
    factory = MagicMock(return_value=service)
    drive_factory = MagicMock()
    gmail_factory = MagicMock()
    monkeypatch.setattr(command, "SessionLocal", lambda: session)
    monkeypatch.setattr(command, "LineageRepository", lambda _session: lineage)
    monkeypatch.setattr(command, "DocumentFilingService", factory)
    monkeypatch.setattr(command, "create_drive_client", drive_factory)
    monkeypatch.setattr(command, "create_gmail_client", gmail_factory)
    settings = SimpleNamespace(
        drive_root_folder_name="Tracework", drive_default_category_folder="Documents",
        attachment_max_size_bytes=1024,
    )
    return SimpleNamespace(**locals())


def test_retry_command_delegates_for_completed_correspondence(monkeypatch):
    deps = _command_dependencies(monkeypatch)

    result = command.retry_document_filing(deps.proposal_id, deps.evaluation_id, deps.settings)

    assert result is deps.service.file_for_project_resolution.return_value
    deps.service.file_for_project_resolution.assert_called_once_with(
        proposal_id=deps.proposal_id, policy_evaluation_id=deps.evaluation_id,
    )
    assert deps.event.processing_state is CorrespondenceProcessingState.COMPLETED
    deps.session.close.assert_called_once()
    deps.gmail_factory.assert_not_called()


def test_retry_content_loader_supplies_actual_bytes(monkeypatch):
    deps = _command_dependencies(monkeypatch)
    download = MagicMock(return_value=SimpleNamespace(content=b"file bytes"))
    monkeypatch.setattr(command, "download_gmail_attachment", download)
    command.retry_document_filing(deps.proposal_id, deps.evaluation_id, deps.settings)
    loader = deps.factory.call_args.kwargs["content_loader"]
    attachment = SimpleNamespace(id=uuid4(), source_attachment_id="api:source-id", size_bytes=10)

    assert loader(deps.event, attachment) == b"file bytes"
    deps.gmail_factory.assert_called_once_with(deps.settings)
    assert download.call_args.kwargs["message_id"] == "message-id"


@pytest.mark.parametrize("invalid", ["missing_proposal", "requirement_proposal", "missing_policy", "wrong_proposal", "wrong_policy"])
def test_invalid_retry_lineage_is_rejected_before_google_access(monkeypatch, invalid):
    deps = _command_dependencies(monkeypatch)
    if invalid == "missing_proposal":
        deps.lineage.get_proposal.return_value = None
    elif invalid == "requirement_proposal":
        deps.proposal.proposal_type = ProposalType.REQUIREMENT_RECONCILIATION
    elif invalid == "missing_policy":
        deps.lineage.get_policy_evaluation_by_id.return_value = None
    elif invalid == "wrong_proposal":
        deps.evaluation.ai_proposal_id = uuid4()
    else:
        deps.evaluation.policy_version = "requirement-policy/1"

    with pytest.raises(ValueError, match="persisted project-resolution"):
        command.retry_document_filing(deps.proposal_id, deps.evaluation_id, deps.settings)

    deps.drive_factory.assert_not_called()
    deps.factory.assert_not_called()
    deps.session.rollback.assert_called_once()
    deps.session.close.assert_called_once()


def test_retry_failure_rolls_back_and_closes_session(monkeypatch):
    deps = _command_dependencies(monkeypatch)
    deps.service.file_for_project_resolution.side_effect = RuntimeError("persistence failed")

    with pytest.raises(RuntimeError):
        command.retry_document_filing(deps.proposal_id, deps.evaluation_id, deps.settings)

    deps.session.rollback.assert_called_once()
    deps.session.close.assert_called_once()
