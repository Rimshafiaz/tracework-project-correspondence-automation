from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import FollowUpCancelReason, FollowUpPurpose, FollowUpStatus
from app.models.follow_up import FollowUp


class FollowUpRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, follow_up_id: UUID) -> FollowUp | None:
        return self.session.get(FollowUp, follow_up_id)

    def get_for_update(self, follow_up_id: UUID) -> FollowUp | None:
        return self.session.scalar(
            select(FollowUp).where(FollowUp.id == follow_up_id).with_for_update()
        )

    def find_active(
        self,
        *,
        requirement_id: UUID,
        purpose: FollowUpPurpose,
        for_update: bool = False,
    ) -> FollowUp | None:
        statement = select(FollowUp).where(
            FollowUp.requirement_id == requirement_id,
            FollowUp.purpose == purpose,
            FollowUp.status.in_((FollowUpStatus.SCHEDULED, FollowUpStatus.DUE)),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def find_by_origin(
        self,
        *,
        requirement_id: UUID,
        purpose: FollowUpPurpose,
        originating_state_transition_id: UUID | None,
        originating_audit_event_id: UUID | None,
    ) -> FollowUp | None:
        if (originating_state_transition_id is None) == (
            originating_audit_event_id is None
        ):
            raise ValueError("exactly one follow-up origin is required")
        origin_filter = (
            FollowUp.originating_state_transition_id
            == originating_state_transition_id
            if originating_state_transition_id is not None
            else FollowUp.originating_audit_event_id == originating_audit_event_id
        )
        return self.session.scalar(
            select(FollowUp).where(
                FollowUp.requirement_id == requirement_id,
                FollowUp.purpose == purpose,
                origin_filter,
            )
        )

    def list_history(
        self,
        *,
        requirement_id: UUID,
        purpose: FollowUpPurpose,
    ) -> Sequence[FollowUp]:
        statement = (
            select(FollowUp)
            .where(
                FollowUp.requirement_id == requirement_id,
                FollowUp.purpose == purpose,
            )
            .order_by(FollowUp.created_at, FollowUp.id)
        )
        return self.session.scalars(statement).all()

    def list_scheduled_due(
        self,
        *,
        on_or_before: date,
        for_update: bool = False,
    ) -> Sequence[FollowUp]:
        statement = (
            select(FollowUp)
            .where(
                FollowUp.status == FollowUpStatus.SCHEDULED,
                FollowUp.due_on <= on_or_before,
            )
            .order_by(FollowUp.due_on, FollowUp.created_at, FollowUp.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).all()

    def claim_scheduled_due(self) -> Sequence[FollowUp]:
        """Lock due rows using the database business date and skip other workers."""
        statement = (
            select(FollowUp)
            .where(
                FollowUp.status == FollowUpStatus.SCHEDULED,
                FollowUp.due_on <= func.current_date(),
            )
            .order_by(FollowUp.due_on, FollowUp.created_at, FollowUp.id)
            .with_for_update(skip_locked=True)
        )
        return self.session.scalars(statement).all()

    def get_due(self, follow_up_id: UUID) -> FollowUp | None:
        return self.session.scalar(
            select(FollowUp).where(
                FollowUp.id == follow_up_id,
                FollowUp.status == FollowUpStatus.DUE,
            )
        )

    def list_actionable_due(self) -> Sequence[FollowUp]:
        statement = (
            select(FollowUp)
            .where(FollowUp.status == FollowUpStatus.DUE)
            .order_by(FollowUp.due_on, FollowUp.became_due_at, FollowUp.id)
        )
        return self.session.scalars(statement).all()

    @staticmethod
    def mark_due(follow_up: FollowUp, *, became_due_at: datetime) -> FollowUp:
        follow_up.status = FollowUpStatus.DUE
        follow_up.became_due_at = became_due_at
        return follow_up

    def create(
        self,
        *,
        project_id: UUID,
        requirement_id: UUID,
        originating_state_transition_id: UUID | None,
        originating_audit_event_id: UUID | None,
        purpose: FollowUpPurpose,
        reason: str,
        expected_date: date,
        due_on: date,
        follow_up_id: UUID | None = None,
    ) -> FollowUp:
        follow_up = FollowUp(
            id=follow_up_id,
            project_id=project_id,
            requirement_id=requirement_id,
            originating_state_transition_id=originating_state_transition_id,
            originating_audit_event_id=originating_audit_event_id,
            purpose=purpose,
            reason=reason,
            expected_date=expected_date,
            due_on=due_on,
            status=FollowUpStatus.SCHEDULED,
        )
        self.session.add(follow_up)
        self.session.flush()
        return follow_up

    @staticmethod
    def update_lifecycle(
        follow_up: FollowUp,
        *,
        status: FollowUpStatus,
        superseded_by_follow_up_id: UUID | None = None,
        cancelled_at: datetime | None = None,
        cancel_reason: FollowUpCancelReason | None = None,
        became_due_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> FollowUp:
        follow_up.status = status
        follow_up.superseded_by_follow_up_id = superseded_by_follow_up_id
        follow_up.cancelled_at = cancelled_at
        follow_up.cancel_reason = cancel_reason
        follow_up.became_due_at = became_due_at
        follow_up.completed_at = completed_at
        return follow_up
