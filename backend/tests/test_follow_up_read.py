from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.follow_up import DueFollowUpContext
from app.models.enums import FollowUpPurpose, FollowUpStatus
from app.repositories.follow_up import FollowUpRepository
from app.services.follow_up_read import (
    FollowUpNotActionableError,
    FollowUpNotFoundError,
    FollowUpReadService,
)


def _follow_up(status=FollowUpStatus.DUE):
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        requirement_id=uuid4(),
        purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
        reason="The requirement remains outstanding after its authoritative expected date.",
        status=status,
        expected_date=date(2026, 10, 10),
        due_on=date(2026, 10, 11),
        became_due_at=datetime(2026, 10, 11, 8, 0, tzinfo=UTC) if status is FollowUpStatus.DUE else None,
        originating_state_transition_id=uuid4(),
        originating_audit_event_id=None,
    )


def test_get_follow_up_returns_complete_typed_context_from_persisted_row():
    row = _follow_up()
    repository = MagicMock(spec=FollowUpRepository)
    repository.get.return_value = row
    service = FollowUpReadService(follow_up_repository=repository)

    context = service.get_follow_up(row.id)

    assert isinstance(context, DueFollowUpContext)
    assert context.model_dump() == {
        "follow_up_id": row.id,
        "project_id": row.project_id,
        "requirement_id": row.requirement_id,
        "purpose": FollowUpPurpose.OVERDUE_REQUIREMENT,
        "reason": row.reason,
        "status": FollowUpStatus.DUE,
        "expected_date": date(2026, 10, 10),
        "due_on": date(2026, 10, 11),
        "became_due_at": row.became_due_at,
        "originating_state_transition_id": row.originating_state_transition_id,
        "originating_audit_event_id": None,
    }
    repository.get.assert_called_once_with(row.id)
    repository.list_actionable_due.assert_not_called()
    repository.create.assert_not_called()
    repository.update_lifecycle.assert_not_called()
    repository.mark_due.assert_not_called()


def test_non_due_follow_up_is_not_returned_as_actionable():
    for status in (FollowUpStatus.SCHEDULED, FollowUpStatus.CANCELLED, FollowUpStatus.COMPLETED):
        row = _follow_up(status)
        repository = MagicMock(spec=FollowUpRepository)
        repository.get.return_value = row
        service = FollowUpReadService(follow_up_repository=repository)

        with pytest.raises(FollowUpNotActionableError):
            service.get_follow_up(row.id)


def test_missing_follow_up_raises_not_found():
    repository = MagicMock(spec=FollowUpRepository)
    repository.get.return_value = None
    service = FollowUpReadService(follow_up_repository=repository)

    with pytest.raises(FollowUpNotFoundError):
        service.get_follow_up(uuid4())


def test_list_due_returns_only_repository_actionable_records_in_order():
    first, second = _follow_up(), _follow_up()
    repository = MagicMock(spec=FollowUpRepository)
    repository.list_actionable_due.return_value = (first, second)
    service = FollowUpReadService(follow_up_repository=repository)

    contexts = service.list_due()

    assert tuple(item.follow_up_id for item in contexts) == (first.id, second.id)
    assert all(item.status is FollowUpStatus.DUE for item in contexts)
    repository.get.assert_not_called()
    repository.create.assert_not_called()
    repository.update_lifecycle.assert_not_called()
    repository.mark_due.assert_not_called()


def test_read_service_only_has_read_repository_operations():
    names = set(FollowUpReadService.__dict__)
    assert "get_follow_up" in names
    assert "list_due" in names
    assert not {"create", "cancel", "reschedule", "promote", "send", "draft"} & names
