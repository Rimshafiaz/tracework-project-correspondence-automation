from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType
from app.models.enums import AttachmentProcessingState, ProjectStatus
from app.services.project_resolution_context import AttachmentContextNotReady, ProjectResolutionContextService


def _service(*, body="Please use TW-001.", attachment=None, sender="owner@example.com"):
    event = SimpleNamespace(
        id=uuid4(),
        source="gmail",
        external_conversation_id="thread-1",
        sender_identifier=sender,
        sender_email=sender,
        sender_name="Owner",
        subject="Project update",
        body=body,
        received_at=datetime(2026, 10, 6, tzinfo=UTC),
    )
    project = SimpleNamespace(
        id=uuid4(),
        project_code="TW-001",
        name="Riverside Works",
        normalized_name="riverside works",
        status=ProjectStatus.ACTIVE,
    )
    contact = SimpleNamespace(
        id=uuid4(),
        project_id=project.id,
        email_normalized=sender,
        is_active=True,
    )
    correspondence = MagicMock()
    correspondence.get.return_value = event
    attachments = MagicMock()
    attachments.list_for_correspondence_event.return_value = (
        (attachment,) if attachment is not None else ()
    )
    projects = MagicMock()
    projects.list_all.return_value = (project,)
    projects.find_by_normalized_codes.side_effect = lambda values: (
        (project,) if "tw-001" in values else ()
    )
    projects.find_by_normalized_names.side_effect = lambda values: (
        (project,) if "riverside works" in values else ()
    )
    identifiers = MagicMock()
    identifiers.list_all_verified_with_projects.return_value = ()
    identifiers.find_verified_exact_with_projects.return_value = ()
    contacts = MagicMock()
    contacts.find_active_with_projects.return_value = ((contact, project),)
    links = MagicMock()
    links.find_approved_links_with_projects_for_conversation.return_value = ()
    service = ProjectResolutionContextService(
        correspondence_repository=correspondence,
        attachment_repository=attachments,
        project_repository=projects,
        identifier_repository=identifiers,
        contact_repository=contacts,
        project_link_repository=links,
    )
    return SimpleNamespace(**locals())


def test_builds_m7_candidate_snapshot_from_persisted_event_and_known_contact():
    deps = _service()

    context = deps.service.build(deps.event.id)

    assert context.correspondence.correspondence_event_id == deps.event.id
    candidate = context.candidates.candidates[0]
    assert candidate.project_id == deps.project.id
    assert {signal.signal_type for signal in candidate.signals} == {
        CandidateSignalType.PROJECT_CODE,
        CandidateSignalType.PROJECT_CONTACT,
    }


def test_known_contact_without_independent_identity_remains_a_contact_only_candidate():
    deps = _service(body="Please review the latest update.")

    context = deps.service.build(deps.event.id)

    assert len(context.candidates.candidates) == 1
    assert tuple(
        signal.signal_type for signal in context.candidates.candidates[0].signals
    ) == (CandidateSignalType.PROJECT_CONTACT,)


def test_verified_identifier_in_attachment_is_scoped_as_document_identity():
    attachment = SimpleNamespace(
        id=uuid4(),
        filename="report.pdf",
        mime_type="application/pdf",
        processing_state=AttachmentProcessingState.EXTRACTED,
        extracted_text="Contract HAK-2026-104 is complete.",
        extraction_metadata={"pdf_segments": []},
    )
    deps = _service(body="See the attached report.", attachment=attachment)
    identifier = SimpleNamespace(
        id=uuid4(),
        project_id=deps.project.id,
        identifier_type="contract",
        display_value="HAK-2026-104",
        normalized_value="hak-2026-104",
        verified=True,
    )
    deps.identifiers.list_all_verified_with_projects.return_value = (
        (identifier, deps.project),
    )
    deps.identifiers.find_verified_exact_with_projects.side_effect = lambda pairs: (
        ((identifier, deps.project),)
        if ("contract", "hak-2026-104") in pairs
        else ()
    )

    context = deps.service.build(deps.event.id)

    document_signal = next(
        signal
        for signal in context.candidates.candidates[0].signals
        if signal.signal_type is CandidateSignalType.DOCUMENT_IDENTIFIER
    )
    assert document_signal.source is CandidateSignalSource.ATTACHMENT
    assert document_signal.attachment_id == attachment.id


def test_pending_attachment_prevents_model_context_from_being_built():
    attachment = SimpleNamespace(
        id=uuid4(),
        filename="report.pdf",
        mime_type="application/pdf",
        processing_state=AttachmentProcessingState.PENDING,
        extracted_text=None,
        extraction_metadata=None,
    )
    deps = _service(attachment=attachment)

    with pytest.raises(AttachmentContextNotReady):
        deps.service.build(deps.event.id)


def test_complete_snapshot_preserves_body_document_identity_conflict():
    attachment = SimpleNamespace(
        id=uuid4(),
        filename="report.pdf",
        mime_type="application/pdf",
        processing_state=AttachmentProcessingState.EXTRACTED,
        extracted_text="Contract BETA-77 applies.",
        extraction_metadata=None,
    )
    deps = _service(body="Use TW-001 for this update.", attachment=attachment)
    other_project = SimpleNamespace(
        id=uuid4(),
        project_code="TW-002",
        name="Northpoint Works",
        normalized_name="northpoint works",
        status=ProjectStatus.ACTIVE,
    )
    identifier = SimpleNamespace(
        id=uuid4(),
        project_id=other_project.id,
        identifier_type="contract",
        display_value="BETA-77",
        normalized_value="beta-77",
        verified=True,
    )
    deps.projects.list_all.return_value = (deps.project, other_project)
    deps.identifiers.list_all_verified_with_projects.return_value = (
        (identifier, other_project),
    )
    deps.identifiers.find_verified_exact_with_projects.side_effect = lambda pairs: (
        ((identifier, other_project),)
        if ("contract", "beta-77") in pairs
        else ()
    )

    context = deps.service.build(deps.event.id)

    candidates = {candidate.project_id: candidate for candidate in context.candidates.candidates}
    assert CandidateSignalType.PROJECT_CODE in {
        signal.signal_type for signal in candidates[deps.project.id].signals
    }
    assert CandidateSignalType.DOCUMENT_IDENTIFIER in {
        signal.signal_type for signal in candidates[other_project.id].signals
    }
