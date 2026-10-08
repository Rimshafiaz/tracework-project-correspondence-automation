import inspect
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.follow_up import DueFollowUpContext
from app.contracts.reply_draft_context import (
    FollowUpReplyScope,
    ReplyDraftEligibility,
    ReplyDraftEligibilityReason,
    ReplyDraftEligibilityStatus,
    ReplyDraftReadLimits,
)
from app.models.enums import (
    DocumentFilingStatus,
    DocumentRevisionStatus,
    EvidenceValidity,
    FollowUpPurpose,
    FollowUpStatus,
    ProjectStatus,
    RequirementState,
)
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.document import DocumentRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.requirement import RequirementRepository
from app.services.follow_up_read import FollowUpReadService
from app.services.reply_draft_eligibility import ReplyDraftEligibilityService
import app.services.scoped_reply_draft_context as scoped_context_module

from app.services.scoped_reply_draft_context import (
    ScopedReplyDraftContextIntegrityError,
    ScopedReplyDraftContextNotDraftableError,
    ScopedReplyDraftContextService,
)


def _fixture():
    project_id = uuid4()
    requirement_id = uuid4()
    follow_up_id = uuid4()
    source_event_id = uuid4()
    scope = FollowUpReplyScope(
        follow_up_id=follow_up_id,
        project_id=project_id,
        requirement_id=requirement_id,
        source_correspondence_event_id=source_event_id,
        trusted_contact_id=uuid4(),
        gmail_message_id="source-message",
        gmail_thread_id="source-thread",
        originating_state_transition_id=uuid4(),
    )
    eligibility = ReplyDraftEligibility(
        status=ReplyDraftEligibilityStatus.DRAFTABLE,
        scope=scope,
    )
    due_context = DueFollowUpContext(
        follow_up_id=follow_up_id,
        project_id=project_id,
        requirement_id=requirement_id,
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        reason="Requirement remains outstanding.",
        status=FollowUpStatus.DUE,
        expected_date=date(2026, 10, 10),
        due_on=date(2026, 10, 11),
        became_due_at=datetime(2026, 10, 11, 8, tzinfo=UTC),
        originating_state_transition_id=scope.originating_state_transition_id,
        originating_audit_event_id=None,
    )
    project = SimpleNamespace(
        id=project_id,
        project_code="TW-001",
        name="Scoped Project",
        status=ProjectStatus.ACTIVE,
    )
    requirement = SimpleNamespace(
        id=requirement_id,
        project_id=project_id,
        name="Submit schedule",
        description="Provide the current schedule.",
        state=RequirementState.OPEN,
        expected_date=date(2026, 10, 10),
    )
    eligibility_service = MagicMock(spec=ReplyDraftEligibilityService)
    follow_up_read = MagicMock(spec=FollowUpReadService)
    projects = MagicMock(spec=ProjectRepository)
    requirements = MagicMock(spec=RequirementRepository)
    correspondence = MagicMock(spec=CorrespondenceEventRepository)
    follow_ups = MagicMock(spec=FollowUpRepository)
    documents = MagicMock(spec=DocumentRepository)
    lineage = MagicMock(spec=LineageRepository)
    eligibility_service.assess.return_value = eligibility
    follow_up_read.get_follow_up.return_value = due_context
    projects.get.return_value = project
    requirements.get.return_value = requirement
    lineage.list_valid_evidence_for_requirements.return_value = ()
    correspondence.list_authoritatively_linked_for_project.return_value = ()
    follow_ups.list_history.return_value = ()
    documents.list_revision_status_for_project.return_value = ()
    service = ScopedReplyDraftContextService(
        eligibility_service=eligibility_service,
        follow_up_read_service=follow_up_read,
        project_repository=projects,
        requirement_repository=requirements,
        correspondence_repository=correspondence,
        follow_up_repository=follow_ups,
        document_repository=documents,
        lineage_repository=lineage,
    )
    return SimpleNamespace(
        service=service,
        scope=scope,
        eligibility=eligibility,
        due_context=due_context,
        project=project,
        requirement=requirement,
        eligibility_service=eligibility_service,
        follow_up_read=follow_up_read,
        projects=projects,
        requirements=requirements,
        correspondence=correspondence,
        follow_ups=follow_ups,
        documents=documents,
        lineage=lineage,
    )


def _evidence(project_id, requirement_id, *, excerpt="evidence", created=0):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        requirement_id=requirement_id,
        correspondence_event_id=uuid4(),
        attachment_id=None,
        source_type="CORRESPONDENCE_BODY",
        excerpt=excerpt,
        page_number=None,
        section=None,
        validity=EvidenceValidity.VALID,
        created=created,
    )


def _correspondence(*, body="body", received_at=None):
    return SimpleNamespace(
        id=uuid4(),
        source="gmail",
        external_event_id="message",
        external_conversation_id="thread",
        sender_identifier="contact@example.com",
        sender_email="contact@example.com",
        sender_name="Contact",
        received_at=received_at or datetime(2026, 10, 11, tzinfo=UTC),
        subject="Subject",
        body=body,
    )


def _history(project_id, requirement_id, *, status=FollowUpStatus.DUE):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        requirement_id=requirement_id,
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        reason="Requirement remains outstanding.",
        expected_date=date(2026, 10, 10),
        due_on=date(2026, 10, 11),
        status=status,
        became_due_at=datetime(2026, 10, 11, tzinfo=UTC),
        cancelled_at=None,
        cancel_reason=None,
        completed_at=None,
    )


def _document(project_id, *, decided_at=None):
    now = datetime(2026, 10, 11, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        source_attachment_id=uuid4(),
        filename="Plan Rev 1.pdf",
        category="Documents",
        filing_status=DocumentFilingStatus.FILED,
        document_family_key="plan",
        revision_label="Rev 1",
        revision_normalized="REV-1",
        revision_order=1,
        revision_status=DocumentRevisionStatus.CURRENT,
        revision_decided_at=decided_at or now,
        created_at=now,
        updated_at=now,
    )


def test_open_rederives_eligibility_from_follow_up_id_only():
    values = _fixture()

    context = values.service.open(values.scope.follow_up_id)

    values.eligibility_service.assess.assert_called_once_with(values.scope.follow_up_id)
    assert context.get_due_follow_up() == values.due_context
    assert tuple(inspect.signature(values.service.open).parameters) == ("follow_up_id",)


def test_not_draftable_follow_up_cannot_open_scoped_context():
    values = _fixture()
    values.eligibility_service.assess.return_value = ReplyDraftEligibility(
        status=ReplyDraftEligibilityStatus.NOT_DRAFTABLE_IN_S2_V1,
        reason=ReplyDraftEligibilityReason.FOLLOW_UP_NOT_DUE,
    )

    with pytest.raises(ScopedReplyDraftContextNotDraftableError) as exc:
        values.service.open(values.scope.follow_up_id)

    assert exc.value.eligibility.reason is ReplyDraftEligibilityReason.FOLLOW_UP_NOT_DUE


def test_context_capabilities_accept_no_model_supplied_scope_or_query_arguments():
    values = _fixture()
    context = values.service.open(values.scope.follow_up_id)

    for name in (
        "get_due_follow_up",
        "get_project_summary",
        "get_requirement_context",
        "list_recent_correspondence",
        "list_follow_up_history",
        "list_document_revision_status",
    ):
        assert tuple(inspect.signature(getattr(context, name)).parameters) == ()


def test_service_accepts_no_public_limit_override():
    assert "limits" not in inspect.signature(ScopedReplyDraftContextService).parameters


def test_module_exposes_no_public_scoped_context_constructor():
    assert "ScopedReplyDraftContext" not in vars(scoped_context_module)


def test_due_follow_up_and_project_summary_are_strictly_scoped():
    values = _fixture()
    context = values.service.open(values.scope.follow_up_id)

    assert context.get_due_follow_up() == values.due_context
    summary = context.get_project_summary()

    assert summary.project_id == values.scope.project_id
    assert summary.project_code == "TW-001"
    values.projects.get.assert_called_once_with(values.scope.project_id)


def test_requirement_context_uses_the_fixed_evidence_limit():
    values = _fixture()
    limits = ReplyDraftReadLimits()
    rows = tuple(
        _evidence(values.scope.project_id, values.scope.requirement_id)
        for _ in range(limits.max_evidence_items + 1)
    )
    values.lineage.list_valid_evidence_for_requirements.return_value = (
        rows
    )
    context = values.service.open(values.scope.follow_up_id)

    result = context.get_requirement_context()

    assert tuple(item.evidence_item_id for item in result.evidence) == tuple(
        item.id for item in rows[: limits.max_evidence_items]
    )
    assert len(result.evidence) == limits.max_evidence_items
    assert result.evidence_limit_reached is True
    values.lineage.list_valid_evidence_for_requirements.assert_called_once_with(
        project_id=values.scope.project_id,
        requirement_ids={values.scope.requirement_id},
        limit=limits.max_evidence_items + 1,
    )


def test_requirement_evidence_mismatch_fails_safely_and_default_prefix_is_marked():
    values = _fixture()
    limits = ReplyDraftReadLimits()
    valid = _evidence(
        values.scope.project_id,
        values.scope.requirement_id,
        excerpt="a" * (limits.max_evidence_excerpt_characters + 1),
    )
    values.lineage.list_valid_evidence_for_requirements.return_value = (valid,)
    context = values.service.open(values.scope.follow_up_id)

    result = context.get_requirement_context()

    assert result.evidence[0].excerpt == "a" * limits.max_evidence_excerpt_characters
    assert result.evidence[0].excerpt_truncated is True
    assert result.evidence[0].is_untrusted_source_data is True
    values.lineage.list_valid_evidence_for_requirements.return_value = (
        _evidence(uuid4(), values.scope.requirement_id),
    )
    with pytest.raises(ScopedReplyDraftContextIntegrityError):
        context.get_requirement_context()


def test_invalid_evidence_is_never_exposed_if_a_repository_contract_breaks():
    values = _fixture()
    invalid = _evidence(values.scope.project_id, values.scope.requirement_id)
    invalid.validity = EvidenceValidity.INVALIDATED
    values.lineage.list_valid_evidence_for_requirements.return_value = (invalid,)
    context = values.service.open(values.scope.follow_up_id)

    with pytest.raises(ScopedReplyDraftContextIntegrityError):
        context.get_requirement_context()


def test_requirement_project_inconsistency_fails_safely():
    values = _fixture()
    values.requirement.project_id = uuid4()
    context = values.service.open(values.scope.follow_up_id)

    with pytest.raises(ScopedReplyDraftContextIntegrityError):
        context.get_requirement_context()


def test_recent_correspondence_uses_fixed_defaults_and_is_marked_untrusted():
    values = _fixture()
    limits = ReplyDraftReadLimits()
    rows = tuple(
        _correspondence(
            body=(
                "a" * (limits.max_correspondence_body_characters + 1)
                if index == 0
                else "body"
            )
        )
        for index in range(limits.max_recent_correspondence + 1)
    )
    values.correspondence.list_authoritatively_linked_for_project.return_value = (
        rows
    )
    context = values.service.open(values.scope.follow_up_id)

    result = context.list_recent_correspondence()

    assert tuple(item.correspondence_event_id for item in result.correspondence) == tuple(
        item.id for item in rows[: limits.max_recent_correspondence]
    )
    assert len(result.correspondence) == limits.max_recent_correspondence
    assert result.limit_reached is True
    assert result.correspondence[0].body == "a" * limits.max_correspondence_body_characters
    assert result.correspondence[0].body_truncated is True
    assert result.correspondence[0].is_untrusted_source_data is True
    values.correspondence.list_authoritatively_linked_for_project.assert_called_once_with(
        project_id=values.scope.project_id,
        limit=limits.max_recent_correspondence + 1,
    )


def test_follow_up_history_uses_the_fixed_limit_and_repository_order():
    values = _fixture()
    limits = ReplyDraftReadLimits()
    rows = tuple(
        _history(values.scope.project_id, values.scope.requirement_id)
        for _ in range(limits.max_follow_up_history + 1)
    )
    values.follow_ups.list_history.return_value = rows
    context = values.service.open(values.scope.follow_up_id)

    result = context.list_follow_up_history()

    assert tuple(item.follow_up_id for item in result.follow_ups) == tuple(
        item.id for item in rows[: limits.max_follow_up_history]
    )
    assert result.limit_reached is True
    values.follow_ups.list_history.assert_called_once_with(
        requirement_id=values.scope.requirement_id,
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        limit=limits.max_follow_up_history + 1,
    )
    values.follow_ups.list_history.return_value = (_history(uuid4(), values.scope.requirement_id),)
    with pytest.raises(ScopedReplyDraftContextIntegrityError):
        context.list_follow_up_history()


def test_document_status_uses_the_fixed_limit_and_never_crosses_scoped_project():
    values = _fixture()
    limits = ReplyDraftReadLimits()
    rows = tuple(
        _document(values.scope.project_id)
        for _ in range(limits.max_document_statuses + 1)
    )
    values.documents.list_revision_status_for_project.return_value = rows
    context = values.service.open(values.scope.follow_up_id)

    result = context.list_document_revision_status()

    assert tuple(item.document_id for item in result.documents) == tuple(
        item.id for item in rows[: limits.max_document_statuses]
    )
    assert len(result.documents) == limits.max_document_statuses
    assert result.limit_reached is True
    values.documents.list_revision_status_for_project.assert_called_once_with(
        project_id=values.scope.project_id,
        limit=limits.max_document_statuses + 1,
    )
    values.documents.list_revision_status_for_project.return_value = (_document(uuid4()),)
    with pytest.raises(ScopedReplyDraftContextIntegrityError):
        context.list_document_revision_status()


@pytest.mark.parametrize("length_delta", (-1, 0, 1))
@pytest.mark.parametrize("kind", ("evidence", "correspondence"))
def test_source_text_truncation_is_an_exact_prefix_at_default_boundaries(
    kind, length_delta
):
    values = _fixture()
    limits = ReplyDraftReadLimits()
    limit = (
        limits.max_evidence_excerpt_characters
        if kind == "evidence"
        else limits.max_correspondence_body_characters
    )
    text = ("A \n\tB" * ((limit + length_delta) // 5 + 1))[: limit + length_delta]
    context = values.service.open(values.scope.follow_up_id)

    if kind == "evidence":
        values.lineage.list_valid_evidence_for_requirements.return_value = (
            _evidence(
                values.scope.project_id,
                values.scope.requirement_id,
                excerpt=text,
            ),
        )
        result = context.get_requirement_context().evidence[0]
        returned_text = result.excerpt
        truncated = result.excerpt_truncated
    else:
        values.correspondence.list_authoritatively_linked_for_project.return_value = (
            _correspondence(body=text),
        )
        result = context.list_recent_correspondence().correspondence[0]
        returned_text = result.body
        truncated = result.body_truncated

    assert returned_text == text[:limit]
    assert truncated is (len(text) > limit)
    assert result.is_untrusted_source_data is True


def test_bounded_contracts_preserve_persisted_grounding_references():
    values = _fixture()
    evidence = _evidence(values.scope.project_id, values.scope.requirement_id)
    evidence.attachment_id = uuid4()
    correspondence = _correspondence()
    document = _document(values.scope.project_id)
    values.lineage.list_valid_evidence_for_requirements.return_value = (evidence,)
    values.correspondence.list_authoritatively_linked_for_project.return_value = (
        correspondence,
    )
    values.documents.list_revision_status_for_project.return_value = (document,)
    context = values.service.open(values.scope.follow_up_id)

    due = context.get_due_follow_up()
    project = context.get_project_summary()
    requirement = context.get_requirement_context()
    recent = context.list_recent_correspondence().correspondence[0]
    document_status = context.list_document_revision_status().documents[0]

    assert due.follow_up_id == values.scope.follow_up_id
    assert project.project_id == values.scope.project_id
    assert requirement.requirement_id == values.scope.requirement_id
    assert requirement.evidence[0].evidence_item_id == evidence.id
    assert requirement.evidence[0].correspondence_event_id == evidence.correspondence_event_id
    assert requirement.evidence[0].attachment_id == evidence.attachment_id
    assert recent.correspondence_event_id == correspondence.id
    assert recent.external_message_id == correspondence.external_event_id
    assert recent.external_conversation_id == correspondence.external_conversation_id
    assert recent.sender_email == correspondence.sender_email
    assert recent.received_at == correspondence.received_at
    assert document_status.document_id == document.id
    assert document_status.source_attachment_id == document.source_attachment_id
    assert document_status.document_family_key == document.document_family_key
    assert document_status.revision_status == document.revision_status


def test_scoped_context_reads_do_not_mutate_or_call_external_providers():
    values = _fixture()
    context = values.service.open(values.scope.follow_up_id)

    context.get_due_follow_up()
    context.get_project_summary()
    context.get_requirement_context()
    context.list_recent_correspondence()
    context.list_follow_up_history()
    context.list_document_revision_status()

    for repository in (
        values.projects,
        values.requirements,
        values.correspondence,
        values.follow_ups,
        values.documents,
        values.lineage,
    ):
        assert not {
            "create",
            "update",
            "update_lifecycle",
            "create_audit_event",
            "mark_due",
        } & {call[0] for call in repository.method_calls}
    assert not hasattr(context, "gmail")
    assert not hasattr(context, "drive")
