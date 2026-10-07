from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.enums import FollowUpPurpose, FollowUpStatus
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.services.follow_up_due import (
    FOLLOW_UP_BECAME_DUE_AUDIT_EVENT,
    FollowUpDueService,
)


def _row(status=FollowUpStatus.SCHEDULED):
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        requirement_id=uuid4(),
        originating_state_transition_id=uuid4(),
        originating_audit_event_id=None,
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        expected_date=date(2026, 10, 10),
        due_on=date(2026, 10, 11),
        reason="The requirement remains outstanding after its expected date.",
        status=status,
        became_due_at=None,
    )


def _service(rows):
    session = MagicMock(spec=Session)
    session.scalar.return_value = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    follow_ups = MagicMock(spec=FollowUpRepository)
    audit = MagicMock(spec=LineageRepository)
    follow_ups.session = session
    audit.session = session
    follow_ups.claim_scheduled_due.return_value = rows
    follow_ups.mark_due.side_effect = FollowUpRepository.mark_due
    service = FollowUpDueService(
        session=session,
        follow_up_repository=follow_ups,
        audit_repository=audit,
    )
    return service, session, follow_ups, audit


def test_due_worker_promotes_row_and_records_one_audit_with_frozen_facts():
    row = _row()
    original = (row.expected_date, row.due_on, row.reason, row.requirement_id, row.project_id)
    service, session, follow_ups, audit = _service((row,))

    result = service.process_due()

    assert result.promoted_follow_up_ids == (row.id,)
    assert row.status is FollowUpStatus.DUE
    assert row.became_due_at == session.scalar.return_value
    assert (row.expected_date, row.due_on, row.reason, row.requirement_id, row.project_id) == original
    follow_ups.claim_scheduled_due.assert_called_once_with()
    session.flush.assert_called_once_with([row])
    audit.create_audit_event.assert_called_once()
    event = audit.create_audit_event.call_args.kwargs
    assert event["event_type"] == FOLLOW_UP_BECAME_DUE_AUDIT_EVENT
    assert event["state_transition_id"] == row.originating_state_transition_id
    assert event["details"] == {
        "follow_up_id": str(row.id),
        "project_id": str(row.project_id),
        "requirement_id": str(row.requirement_id),
        "purpose": "OVERDUE_REQUIREMENT",
        "expected_date": "2026-10-10",
        "due_on": "2026-10-11",
        "became_due_at": session.scalar.return_value.isoformat(),
        "originating_state_transition_id": str(row.originating_state_transition_id),
        "originating_audit_event_id": None,
        "previous_status": "SCHEDULED",
        "new_status": "DUE",
    }


def test_due_worker_retry_has_no_mutation_or_duplicate_audit():
    service, session, follow_ups, audit = _service(())

    result = service.process_due()

    assert result.promoted_count == 0
    session.scalar.assert_not_called()
    session.flush.assert_not_called()
    audit.create_audit_event.assert_not_called()
    follow_ups.claim_scheduled_due.assert_called_once_with()


def test_overlapping_due_worker_result_cannot_duplicate_promotion_or_audit():
    row = _row()
    service, session, follow_ups, audit = _service((row,))
    follow_ups.claim_scheduled_due.side_effect = ((row,), (row,))

    first = service.process_due()
    second = service.process_due()

    assert first.promoted_follow_up_ids == (row.id,)
    assert second.promoted_follow_up_ids == ()
    assert row.status is FollowUpStatus.DUE
    assert follow_ups.mark_due.call_count == 1
    assert audit.create_audit_event.call_count == 1
    assert session.flush.call_count == 1


@pytest.mark.parametrize(
    "status",
    [FollowUpStatus.DUE, FollowUpStatus.CANCELLED, FollowUpStatus.COMPLETED],
)
def test_stale_non_scheduled_rows_are_never_promoted(status):
    row = _row(status)
    service, session, _, audit = _service((row,))

    result = service.process_due()

    assert result.promoted_follow_up_ids == ()
    assert row.status is status
    session.flush.assert_not_called()
    audit.create_audit_event.assert_not_called()


def test_worker_claim_query_uses_database_current_date_and_skip_locked():
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = ()
    repository = FollowUpRepository(session)

    repository.claim_scheduled_due()

    statement = session.scalars.call_args.args[0]
    assert "CURRENT_DATE" in str(statement)
    assert "follow_ups.due_on <= CURRENT_DATE" in str(statement)
    assert "follow_ups.status" in str(statement)
    assert statement._for_update_arg.skip_locked is True
    assert "ORDER BY follow_ups.due_on, follow_ups.created_at, follow_ups.id" in str(statement)


def test_actionable_due_query_filters_only_due_and_is_ordered():
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = ()
    repository = FollowUpRepository(session)

    assert repository.list_actionable_due() == ()

    statement = session.scalars.call_args.args[0]
    assert "follow_ups.status" in str(statement)
    assert "ORDER BY follow_ups.due_on, follow_ups.became_due_at, follow_ups.id" in str(statement)
    assert "CANCELLED" not in str(statement)
    assert "COMPLETED" not in str(statement)
    assert "SCHEDULED" not in str(statement)
