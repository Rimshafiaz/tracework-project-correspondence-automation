from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.reply_draft_context import (
    ReplyDraftEligibilityReason,
    ReplyDraftEligibilityStatus,
    ReplyDraftReadLimits,
)
from app.models.enums import FollowUpStatus, TransitionStatus
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import (
    CorrespondenceProjectLinkRepository,
)
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.requirement import RequirementRepository
from app.services.reply_draft_eligibility import (
    ReplyDraftEligibilityNotFoundError,
    ReplyDraftEligibilityService,
)


def _service(*, follow_up_status=FollowUpStatus.DUE):
    project_id = uuid4()
    requirement_id = uuid4()
    event_id = uuid4()
    transition_id = uuid4()
    proposal_id = uuid4()
    follow_up = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        requirement_id=requirement_id,
        status=follow_up_status,
        originating_state_transition_id=transition_id,
        originating_audit_event_id=None,
    )
    requirement = SimpleNamespace(id=requirement_id, project_id=project_id)
    transition = SimpleNamespace(
        id=transition_id,
        ai_proposal_id=proposal_id,
        status=TransitionStatus.APPLIED,
    )
    proposal = SimpleNamespace(id=proposal_id, correspondence_event_id=event_id)
    event = SimpleNamespace(
        id=event_id,
        source="gmail",
        sender_email="contact@example.com",
        external_event_id="gmail-message-1",
        external_conversation_id="gmail-thread-1",
        received_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    contact = SimpleNamespace(id=uuid4(), project_id=project_id, is_active=True)

    follow_ups = MagicMock(spec=FollowUpRepository)
    requirements = MagicMock(spec=RequirementRepository)
    lineage = MagicMock(spec=LineageRepository)
    correspondence = MagicMock(spec=CorrespondenceEventRepository)
    links = MagicMock(spec=CorrespondenceProjectLinkRepository)
    contacts = MagicMock(spec=ProjectContactRepository)
    follow_ups.get.return_value = follow_up
    requirements.get.return_value = requirement
    lineage.get_state_transition_by_id.return_value = transition
    lineage.get_proposal.return_value = proposal
    correspondence.get.return_value = event
    links.get_approved_link.return_value = SimpleNamespace(id=uuid4())
    links.list_approved_project_ids_for_event.return_value = (project_id,)
    contacts.get_active_for_project_email.return_value = contact
    service = ReplyDraftEligibilityService(
        follow_up_repository=follow_ups,
        requirement_repository=requirements,
        lineage_repository=lineage,
        correspondence_repository=correspondence,
        project_link_repository=links,
        contact_repository=contacts,
    )
    return SimpleNamespace(
        service=service,
        follow_up=follow_up,
        requirement=requirement,
        transition=transition,
        proposal=proposal,
        event=event,
        contact=contact,
        follow_ups=follow_ups,
        requirements=requirements,
        lineage=lineage,
        correspondence=correspondence,
        links=links,
        contacts=contacts,
    )


def _assert_ineligible(result, reason):
    assert result.status is ReplyDraftEligibilityStatus.NOT_DRAFTABLE_IN_S2_V1
    assert result.reason is reason
    assert result.scope is None


def test_due_correspondence_origin_is_draftable_with_derived_scope():
    values = _service()
    values.event.sender_email = " Contact@Example.Com "

    result = values.service.assess(values.follow_up.id)

    assert result.status is ReplyDraftEligibilityStatus.DRAFTABLE
    assert result.reason is None
    assert result.scope is not None
    assert result.scope.follow_up_id == values.follow_up.id
    assert result.scope.project_id == values.follow_up.project_id
    assert result.scope.requirement_id == values.follow_up.requirement_id
    assert result.scope.source_correspondence_event_id == values.event.id
    assert result.scope.trusted_contact_id == values.contact.id
    assert result.scope.gmail_message_id == "gmail-message-1"
    assert result.scope.gmail_thread_id == "gmail-thread-1"
    values.contacts.get_active_for_project_email.assert_called_once_with(
        project_id=values.follow_up.project_id,
        email_normalized="contact@example.com",
    )


@pytest.mark.parametrize(
    "status",
    (FollowUpStatus.SCHEDULED, FollowUpStatus.CANCELLED, FollowUpStatus.COMPLETED),
)
def test_existing_non_due_follow_up_has_typed_not_due_result(status):
    values = _service(follow_up_status=status)

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(result, ReplyDraftEligibilityReason.FOLLOW_UP_NOT_DUE)
    values.requirements.get.assert_not_called()
    values.lineage.get_state_transition_by_id.assert_not_called()


def test_missing_follow_up_uses_not_found_convention():
    values = _service()
    values.follow_ups.get.return_value = None

    with pytest.raises(ReplyDraftEligibilityNotFoundError):
        values.service.assess(uuid4())


@pytest.mark.parametrize(
    "kind",
    ("missing_transition", "missing_proposal", "unapplied_transition"),
)
def test_broken_state_transition_lineage_is_rejected(kind):
    values = _service()
    if kind == "missing_transition":
        values.lineage.get_state_transition_by_id.return_value = None
    elif kind == "missing_proposal":
        values.lineage.get_proposal.return_value = None
    else:
        values.transition.status = TransitionStatus.PREVIEWED

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(result, ReplyDraftEligibilityReason.MISSING_AUTHORITATIVE_LINEAGE)


def test_setup_origin_without_correspondence_is_not_draftable():
    values = _service()
    values.follow_up.originating_state_transition_id = None
    values.follow_up.originating_audit_event_id = uuid4()
    values.lineage.get_audit_event_by_id.return_value = SimpleNamespace(
        id=values.follow_up.originating_audit_event_id,
        project_id=values.follow_up.project_id,
        requirement_id=values.follow_up.requirement_id,
        correspondence_event_id=None,
    )

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(result, ReplyDraftEligibilityReason.MISSING_SOURCE_CORRESPONDENCE)


def test_missing_persisted_source_correspondence_is_rejected():
    values = _service()
    values.correspondence.get.return_value = None

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(result, ReplyDraftEligibilityReason.MISSING_SOURCE_CORRESPONDENCE)


def test_audit_origin_with_real_consistent_correspondence_can_be_draftable():
    values = _service()
    values.follow_up.originating_state_transition_id = None
    values.follow_up.originating_audit_event_id = uuid4()
    values.lineage.get_audit_event_by_id.return_value = SimpleNamespace(
        id=values.follow_up.originating_audit_event_id,
        project_id=values.follow_up.project_id,
        requirement_id=values.follow_up.requirement_id,
        correspondence_event_id=values.event.id,
    )

    result = values.service.assess(values.follow_up.id)

    assert result.status is ReplyDraftEligibilityStatus.DRAFTABLE


@pytest.mark.parametrize(
    "case, reason",
    (
        ("no_link", ReplyDraftEligibilityReason.NO_AUTHORITATIVE_PROJECT_LINK),
        ("wrong_requirement_project", ReplyDraftEligibilityReason.INCONSISTENT_LINEAGE),
        ("untrusted_sender", ReplyDraftEligibilityReason.SENDER_NOT_ACTIVE_TRUSTED_CONTACT),
        ("unsupported_source", ReplyDraftEligibilityReason.UNSUPPORTED_SOURCE),
        ("missing_message", ReplyDraftEligibilityReason.MISSING_GMAIL_SOURCE_METADATA),
        ("missing_thread", ReplyDraftEligibilityReason.MISSING_GMAIL_SOURCE_METADATA),
    ),
)
def test_project_sender_and_gmail_safety_failures_are_rejected(case, reason):
    values = _service()
    if case == "no_link":
        values.links.get_approved_link.return_value = None
        values.links.list_approved_project_ids_for_event.return_value = ()
    elif case == "wrong_requirement_project":
        values.requirement.project_id = uuid4()
    elif case == "untrusted_sender":
        values.contacts.get_active_for_project_email.return_value = None
    elif case == "unsupported_source":
        values.event.source = "imap"
    elif case == "missing_message":
        values.event.external_event_id = " "
    elif case == "missing_thread":
        values.event.external_conversation_id = None

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(result, reason)


def test_inactive_trusted_contact_is_rejected_even_if_repository_contract_is_broken():
    values = _service()
    values.contacts.get_active_for_project_email.return_value = SimpleNamespace(
        id=values.contact.id,
        project_id=values.follow_up.project_id,
        is_active=False,
    )

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(
        result, ReplyDraftEligibilityReason.SENDER_NOT_ACTIVE_TRUSTED_CONTACT
    )


def test_audit_project_or_requirement_mismatch_is_rejected():
    values = _service()
    values.follow_up.originating_state_transition_id = None
    values.follow_up.originating_audit_event_id = uuid4()
    values.lineage.get_audit_event_by_id.return_value = SimpleNamespace(
        id=values.follow_up.originating_audit_event_id,
        project_id=uuid4(),
        requirement_id=values.follow_up.requirement_id,
        correspondence_event_id=values.event.id,
    )

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(result, ReplyDraftEligibilityReason.INCONSISTENT_LINEAGE)


def test_correspondence_linked_only_to_another_project_is_rejected():
    values = _service()
    values.links.get_approved_link.return_value = None
    values.links.list_approved_project_ids_for_event.return_value = (uuid4(),)

    result = values.service.assess(values.follow_up.id)

    _assert_ineligible(
        result, ReplyDraftEligibilityReason.SOURCE_PROJECT_MISMATCH
    )


def test_eligibility_is_read_only_and_limits_are_frozen():
    values = _service()

    values.service.assess(values.follow_up.id)

    for repository in (
        values.follow_ups,
        values.requirements,
        values.lineage,
        values.correspondence,
        values.links,
        values.contacts,
    ):
        assert not {
            "create",
            "update",
            "update_lifecycle",
            "mark_due",
            "create_audit_event",
        } & {
            call[0] for call in repository.method_calls
        }
    limits = ReplyDraftReadLimits()
    with pytest.raises(Exception):
        limits.max_evidence_items = 1
