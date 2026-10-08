from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.enums import FollowUpCancelReason, FollowUpPurpose, FollowUpStatus
from app.repositories.follow_up import FollowUpRepository


def test_repository_creates_scheduled_follow_up_without_lifecycle_decisions():
    session = MagicMock()
    repository = FollowUpRepository(session)
    transition_id = uuid4()

    result = repository.create(
        project_id=uuid4(),
        requirement_id=uuid4(),
        originating_state_transition_id=transition_id,
        originating_audit_event_id=None,
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        reason="The requirement remains outstanding after its expected date.",
        expected_date=date(2026, 10, 10),
        due_on=date(2026, 10, 11),
    )

    assert result.status is FollowUpStatus.SCHEDULED
    assert result.originating_state_transition_id == transition_id
    assert session.add.call_count == 1
    session.flush.assert_called_once_with()


def test_repository_active_lookup_can_lock_rows():
    session = MagicMock()
    repository = FollowUpRepository(session)

    repository.find_active(
        requirement_id=uuid4(),
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        for_update=True,
    )

    statement = session.scalar.call_args.args[0]
    rendered = str(statement)
    assert "follow_ups.requirement_id" in rendered
    assert "follow_ups.status IN" in rendered
    assert statement._for_update_arg is not None


def test_repository_due_query_is_deterministic_and_lockable():
    session = MagicMock()
    session.scalars.return_value.all.return_value = ()
    repository = FollowUpRepository(session)

    result = repository.list_scheduled_due(
        on_or_before=date(2026, 10, 11),
        for_update=True,
    )

    assert result == ()
    statement = session.scalars.call_args.args[0]
    rendered = str(statement)
    assert "follow_ups.status" in rendered
    assert "follow_ups.due_on" in rendered
    assert "ORDER BY follow_ups.due_on, follow_ups.created_at, follow_ups.id" in rendered
    assert statement._for_update_arg is not None


def test_repository_history_is_deterministic():
    session = MagicMock()
    session.scalars.return_value.all.return_value = ()
    repository = FollowUpRepository(session)

    assert repository.list_history(
        requirement_id=uuid4(),
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
    ) == ()

    statement = session.scalars.call_args.args[0]
    assert "ORDER BY follow_ups.created_at, follow_ups.id" in str(statement)


def test_repository_history_accepts_a_positive_bound():
    session = MagicMock()
    session.scalars.return_value.all.return_value = ()
    repository = FollowUpRepository(session)

    assert repository.list_history(
        requirement_id=uuid4(),
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        limit=13,
    ) == ()

    statement = session.scalars.call_args.args[0]
    assert "LIMIT" in str(statement)


def test_repository_mechanically_updates_lifecycle_fields():
    session = MagicMock()
    repository = FollowUpRepository(session)
    follow_up = repository.create(
        project_id=uuid4(),
        requirement_id=uuid4(),
        originating_state_transition_id=None,
        originating_audit_event_id=uuid4(),
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        reason="The requirement remains outstanding after its expected date.",
        expected_date=date(2026, 10, 10),
        due_on=date(2026, 10, 11),
    )
    now = datetime.now(UTC)

    result = repository.update_lifecycle(
        follow_up,
        status=FollowUpStatus.CANCELLED,
        cancelled_at=now,
        cancel_reason=FollowUpCancelReason.REQUIREMENT_SATISFIED,
    )

    assert result is follow_up
    assert result.status is FollowUpStatus.CANCELLED
    assert result.cancelled_at == now
    assert result.cancel_reason is FollowUpCancelReason.REQUIREMENT_SATISFIED
