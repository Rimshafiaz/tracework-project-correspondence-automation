from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.enums import (
    FollowUpCancelReason,
    FollowUpPurpose,
    FollowUpStatus,
    RequirementState,
)
from app.models.follow_up import FollowUp
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.services.follow_up_lifecycle import (
    FOLLOW_UP_CANCELLED_AUDIT_EVENT,
    FOLLOW_UP_RESCHEDULED_AUDIT_EVENT,
    FOLLOW_UP_SCHEDULED_AUDIT_EVENT,
    FollowUpLifecycleAction,
    FollowUpLifecycleService,
)


def _requirement(*, state=RequirementState.OPEN, expected_date=date(2026, 10, 10)):
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        state=state,
        expected_date=expected_date,
    )


def _active(requirement, *, expected_date=None, status=FollowUpStatus.SCHEDULED):
    expected = expected_date or requirement.expected_date
    return SimpleNamespace(
        id=uuid4(),
        project_id=requirement.project_id,
        requirement_id=requirement.id,
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        expected_date=expected,
        due_on=expected.replace(day=expected.day + 1),
        status=status,
        became_due_at=(datetime.now(UTC) if status is FollowUpStatus.DUE else None),
        superseded_by_follow_up_id=None,
        cancelled_at=None,
        cancel_reason=None,
        completed_at=None,
    )


def _service(requirement, *, active=None, existing_origin=None):
    session = MagicMock(spec=Session)
    requirements = MagicMock(spec=RequirementRepository)
    follow_ups = MagicMock(spec=FollowUpRepository)
    audit = MagicMock(spec=LineageRepository)
    for dependency in (requirements, follow_ups, audit):
        dependency.session = session
    requirements.get_for_update.return_value = requirement
    follow_ups.find_by_origin.return_value = existing_origin
    follow_ups.find_active.return_value = active

    def create(**values):
        values["id"] = values.pop("follow_up_id", None) or uuid4()
        values["status"] = FollowUpStatus.SCHEDULED
        values["became_due_at"] = None
        values["cancelled_at"] = None
        values["cancel_reason"] = None
        values["completed_at"] = None
        values["superseded_by_follow_up_id"] = None
        return SimpleNamespace(**values)

    follow_ups.create.side_effect = create

    def update(item, **values):
        for key, value in values.items():
            setattr(item, key, value)
        return item

    follow_ups.update_lifecycle.side_effect = update
    service = FollowUpLifecycleService(
        session=session,
        requirement_repository=requirements,
        follow_up_repository=follow_ups,
        audit_repository=audit,
    )
    return service, session, requirements, follow_ups, audit


@pytest.mark.parametrize("state", [RequirementState.OPEN, RequirementState.PARTIAL])
def test_qualifying_authoritative_requirement_is_scheduled(state):
    requirement = _requirement(state=state)
    service, _, requirements, follow_ups, audit = _service(requirement)
    transition_id = uuid4()

    result = service.reconcile(
        requirement.id,
        originating_state_transition_id=transition_id,
    )

    assert result.action is FollowUpLifecycleAction.SCHEDULED
    assert result.follow_up.expected_date == date(2026, 10, 10)
    assert result.follow_up.due_on == date(2026, 10, 11)
    requirements.get_for_update.assert_called_once_with(requirement.id)
    assert follow_ups.find_active.call_args.kwargs["for_update"] is True
    assert audit.create_audit_event.call_args.kwargs["event_type"] == FOLLOW_UP_SCHEDULED_AUDIT_EVENT


@pytest.mark.parametrize(
    "state,expected_date",
    [
        (RequirementState.REVIEW, date(2026, 10, 10)),
        (RequirementState.SATISFIED, date(2026, 10, 10)),
        (RequirementState.RETRACTED, date(2026, 10, 10)),
        (RequirementState.OPEN, None),
        (RequirementState.PARTIAL, None),
    ],
)
def test_nonqualifying_requirement_without_active_follow_up_creates_nothing(state, expected_date):
    requirement = _requirement(state=state, expected_date=expected_date)
    service, _, _, follow_ups, audit = _service(requirement)

    result = service.reconcile(
        requirement.id,
        originating_state_transition_id=uuid4(),
    )

    assert result.action is FollowUpLifecycleAction.NO_ACTION
    follow_ups.create.assert_not_called()
    follow_ups.update_lifecycle.assert_not_called()
    audit.create_audit_event.assert_not_called()


def test_same_origin_retry_reuses_schedule_without_duplicate_audit():
    requirement = _requirement()
    existing = _active(requirement)
    service, _, _, follow_ups, audit = _service(
        requirement,
        existing_origin=existing,
    )

    result = service.reconcile(
        requirement.id,
        originating_audit_event_id=uuid4(),
    )

    assert result.action is FollowUpLifecycleAction.REUSED
    assert result.follow_up is existing
    follow_ups.find_active.assert_not_called()
    follow_ups.create.assert_not_called()
    audit.create_audit_event.assert_not_called()


def test_unchanged_expected_date_reuses_active_schedule():
    requirement = _requirement()
    active = _active(requirement)
    service, _, _, follow_ups, audit = _service(requirement, active=active)

    result = service.reconcile(
        requirement.id,
        originating_state_transition_id=uuid4(),
    )

    assert result.action is FollowUpLifecycleAction.REUSED
    assert result.follow_up is active
    follow_ups.create.assert_not_called()
    audit.create_audit_event.assert_not_called()


def test_expected_date_change_cancels_old_and_creates_linked_replacement():
    requirement = _requirement(expected_date=date(2026, 10, 20))
    active = _active(requirement, expected_date=date(2026, 10, 10))
    service, session, _, follow_ups, audit = _service(requirement, active=active)
    transition_id = uuid4()

    result = service.reconcile(
        requirement.id,
        originating_state_transition_id=transition_id,
    )

    assert result.action is FollowUpLifecycleAction.RESCHEDULED
    assert active.status is FollowUpStatus.CANCELLED
    assert active.cancel_reason is FollowUpCancelReason.EXPECTED_DATE_CHANGED
    assert active.superseded_by_follow_up_id == result.follow_up.id
    assert result.follow_up.expected_date == date(2026, 10, 20)
    assert result.follow_up.due_on == date(2026, 10, 21)
    session.flush.assert_called_once_with([active])
    assert audit.create_audit_event.call_args.kwargs["event_type"] == FOLLOW_UP_RESCHEDULED_AUDIT_EVENT


@pytest.mark.parametrize(
    "state,expected_date,reason",
    [
        (RequirementState.OPEN, None, FollowUpCancelReason.EXPECTED_DATE_REMOVED),
        (RequirementState.SATISFIED, date(2026, 10, 10), FollowUpCancelReason.REQUIREMENT_SATISFIED),
        (RequirementState.RETRACTED, date(2026, 10, 10), FollowUpCancelReason.REQUIREMENT_RETRACTED),
    ],
)
@pytest.mark.parametrize("active_status", [FollowUpStatus.SCHEDULED, FollowUpStatus.DUE])
def test_authoritative_nonactionable_state_cancels_active_follow_up(state, expected_date, reason, active_status):
    requirement = _requirement(state=state, expected_date=expected_date)
    source = _requirement(expected_date=date(2026, 10, 10))
    source.id = requirement.id
    source.project_id = requirement.project_id
    active = _active(source, status=active_status)
    service, _, _, follow_ups, audit = _service(requirement, active=active)

    result = service.reconcile(
        requirement.id,
        originating_state_transition_id=uuid4(),
    )

    assert result.action is FollowUpLifecycleAction.CANCELLED
    assert active.status is FollowUpStatus.CANCELLED
    assert active.cancel_reason is reason
    follow_ups.create.assert_not_called()
    assert audit.create_audit_event.call_args.kwargs["event_type"] == FOLLOW_UP_CANCELLED_AUDIT_EVENT


def test_lifecycle_does_not_call_ai_gmail_or_document_services():
    constructor_names = set(FollowUpLifecycleService.__init__.__code__.co_varnames)
    assert "agent" not in constructor_names
    assert "gmail" not in constructor_names
    assert "document" not in constructor_names
