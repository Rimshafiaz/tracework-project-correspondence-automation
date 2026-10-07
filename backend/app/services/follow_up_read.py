from collections.abc import Sequence
from uuid import UUID

from app.contracts.follow_up import DueFollowUpContext
from app.models.enums import FollowUpStatus
from app.models.follow_up import FollowUp
from app.repositories.follow_up import FollowUpRepository


class FollowUpNotFoundError(LookupError):
    pass


class FollowUpNotActionableError(ValueError):
    pass


class FollowUpReadService:
    """Read-only boundary for actionable, persisted follow-up context."""

    def __init__(self, *, follow_up_repository: FollowUpRepository) -> None:
        self.follow_ups = follow_up_repository

    def get_follow_up(self, follow_up_id: UUID) -> DueFollowUpContext:
        follow_up = self.follow_ups.get(follow_up_id)
        if follow_up is None:
            raise FollowUpNotFoundError("follow-up was not found")
        if follow_up.status is not FollowUpStatus.DUE:
            raise FollowUpNotActionableError("follow-up is not due and actionable")
        return self._context(follow_up)

    def list_due(self) -> Sequence[DueFollowUpContext]:
        return tuple(
            self._context(follow_up)
            for follow_up in self.follow_ups.list_actionable_due()
        )

    @staticmethod
    def _context(follow_up: FollowUp) -> DueFollowUpContext:
        if (
            follow_up.status is not FollowUpStatus.DUE
            or follow_up.became_due_at is None
        ):
            raise ValueError("persisted due follow-up is incomplete")
        return DueFollowUpContext(
            follow_up_id=follow_up.id,
            project_id=follow_up.project_id,
            requirement_id=follow_up.requirement_id,
            purpose=follow_up.purpose,
            reason=follow_up.reason,
            status=follow_up.status,
            expected_date=follow_up.expected_date,
            due_on=follow_up.due_on,
            became_due_at=follow_up.became_due_at,
            originating_state_transition_id=follow_up.originating_state_transition_id,
            originating_audit_event_id=follow_up.originating_audit_event_id,
        )
