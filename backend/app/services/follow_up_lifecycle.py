from dataclasses import dataclass
from datetime import UTC, timedelta, datetime
from enum import StrEnum
from uuid import UUID, uuid4

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

FOLLOW_UP_SCHEDULED_AUDIT_EVENT = "follow_up_scheduled"
FOLLOW_UP_RESCHEDULED_AUDIT_EVENT = "follow_up_rescheduled"
FOLLOW_UP_CANCELLED_AUDIT_EVENT = "follow_up_cancelled"
OVERDUE_REQUIREMENT_REASON = (
    "The requirement remains outstanding after its authoritative expected date."
)


class FollowUpLifecycleAction(StrEnum):
    SCHEDULED = "SCHEDULED"
    REUSED = "REUSED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class FollowUpLifecycleResult:
    action: FollowUpLifecycleAction
    follow_up: FollowUp | None
    previous_follow_up: FollowUp | None = None


class FollowUpLifecycleService:
    def __init__(
        self,
        *,
        session: Session,
        requirement_repository: RequirementRepository,
        follow_up_repository: FollowUpRepository,
        audit_repository: LineageRepository,
    ) -> None:
        repositories = (
            requirement_repository,
            follow_up_repository,
            audit_repository,
        )
        if any(repository.session is not session for repository in repositories):
            raise ValueError("follow-up lifecycle repositories must share one session")
        self.session = session
        self.requirements = requirement_repository
        self.follow_ups = follow_up_repository
        self.audit = audit_repository

    def reconcile(
        self,
        requirement_id: UUID,
        *,
        originating_state_transition_id: UUID | None = None,
        originating_audit_event_id: UUID | None = None,
        correspondence_event_id: UUID | None = None,
        ai_proposal_id: UUID | None = None,
        policy_evaluation_id: UUID | None = None,
        actor_type: str = "system",
        actor_identifier: str | None = None,
    ) -> FollowUpLifecycleResult:
        if (originating_state_transition_id is None) == (
            originating_audit_event_id is None
        ):
            raise ValueError("exactly one authoritative follow-up origin is required")

        requirement = self.requirements.get_for_update(requirement_id)
        if requirement is None:
            raise LookupError("authoritative requirement was not found")

        existing_for_origin = self.follow_ups.find_by_origin(
            requirement_id=requirement.id,
            purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
            originating_state_transition_id=originating_state_transition_id,
            originating_audit_event_id=originating_audit_event_id,
        )
        if existing_for_origin is not None:
            return FollowUpLifecycleResult(
                action=FollowUpLifecycleAction.REUSED,
                follow_up=existing_for_origin,
            )

        active = self.follow_ups.find_active(
            requirement_id=requirement.id,
            purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
            for_update=True,
        )

        qualifies = (
            requirement.state in (RequirementState.OPEN, RequirementState.PARTIAL)
            and requirement.expected_date is not None
        )
        if qualifies:
            if active is not None and active.expected_date == requirement.expected_date:
                return FollowUpLifecycleResult(
                    action=FollowUpLifecycleAction.REUSED,
                    follow_up=active,
                )
            if active is not None:
                return self._reschedule(
                    requirement=requirement,
                    active=active,
                    originating_state_transition_id=originating_state_transition_id,
                    originating_audit_event_id=originating_audit_event_id,
                    correspondence_event_id=correspondence_event_id,
                    ai_proposal_id=ai_proposal_id,
                    policy_evaluation_id=policy_evaluation_id,
                    actor_type=actor_type,
                    actor_identifier=actor_identifier,
                )
            created = self._create_schedule(
                requirement=requirement,
                originating_state_transition_id=originating_state_transition_id,
                originating_audit_event_id=originating_audit_event_id,
            )
            self._audit(
                FOLLOW_UP_SCHEDULED_AUDIT_EVENT,
                requirement=requirement,
                follow_up=created,
                originating_state_transition_id=originating_state_transition_id,
                originating_audit_event_id=originating_audit_event_id,
                correspondence_event_id=correspondence_event_id,
                ai_proposal_id=ai_proposal_id,
                policy_evaluation_id=policy_evaluation_id,
                actor_type=actor_type,
                actor_identifier=actor_identifier,
            )
            return FollowUpLifecycleResult(
                action=FollowUpLifecycleAction.SCHEDULED,
                follow_up=created,
            )

        cancel_reason = self._cancel_reason(requirement.state, requirement.expected_date)
        if active is None or cancel_reason is None:
            return FollowUpLifecycleResult(
                action=FollowUpLifecycleAction.NO_ACTION,
                follow_up=None,
            )
        now = datetime.now(UTC)
        self.follow_ups.update_lifecycle(
            active,
            status=FollowUpStatus.CANCELLED,
            cancelled_at=now,
            cancel_reason=cancel_reason,
            became_due_at=active.became_due_at,
        )
        self._audit(
            FOLLOW_UP_CANCELLED_AUDIT_EVENT,
            requirement=requirement,
            follow_up=active,
            originating_state_transition_id=originating_state_transition_id,
            originating_audit_event_id=originating_audit_event_id,
            correspondence_event_id=correspondence_event_id,
            ai_proposal_id=ai_proposal_id,
            policy_evaluation_id=policy_evaluation_id,
            actor_type=actor_type,
            actor_identifier=actor_identifier,
            cancellation_reason=cancel_reason,
        )
        return FollowUpLifecycleResult(
            action=FollowUpLifecycleAction.CANCELLED,
            follow_up=active,
        )

    def _create_schedule(
        self,
        *,
        requirement,
        originating_state_transition_id: UUID | None,
        originating_audit_event_id: UUID | None,
        follow_up_id: UUID | None = None,
    ) -> FollowUp:
        return self.follow_ups.create(
            follow_up_id=follow_up_id,
            project_id=requirement.project_id,
            requirement_id=requirement.id,
            originating_state_transition_id=originating_state_transition_id,
            originating_audit_event_id=originating_audit_event_id,
            purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
            reason=OVERDUE_REQUIREMENT_REASON,
            expected_date=requirement.expected_date,
            due_on=requirement.expected_date + timedelta(days=1),
        )

    def _reschedule(
        self,
        *,
        requirement,
        active: FollowUp,
        originating_state_transition_id: UUID | None,
        originating_audit_event_id: UUID | None,
        correspondence_event_id: UUID | None,
        ai_proposal_id: UUID | None,
        policy_evaluation_id: UUID | None,
        actor_type: str,
        actor_identifier: str | None,
    ) -> FollowUpLifecycleResult:
        replacement_id = uuid4()
        now = datetime.now(UTC)
        self.follow_ups.update_lifecycle(
            active,
            status=FollowUpStatus.CANCELLED,
            superseded_by_follow_up_id=replacement_id,
            cancelled_at=now,
            cancel_reason=FollowUpCancelReason.EXPECTED_DATE_CHANGED,
            became_due_at=active.became_due_at,
        )
        # The old row must stop being active before the replacement is flushed.
        self.session.flush([active])
        replacement = self._create_schedule(
            requirement=requirement,
            originating_state_transition_id=originating_state_transition_id,
            originating_audit_event_id=originating_audit_event_id,
            follow_up_id=replacement_id,
        )
        self._audit(
            FOLLOW_UP_RESCHEDULED_AUDIT_EVENT,
            requirement=requirement,
            follow_up=replacement,
            originating_state_transition_id=originating_state_transition_id,
            originating_audit_event_id=originating_audit_event_id,
            correspondence_event_id=correspondence_event_id,
            ai_proposal_id=ai_proposal_id,
            policy_evaluation_id=policy_evaluation_id,
            actor_type=actor_type,
            actor_identifier=actor_identifier,
            previous_follow_up=active,
            cancellation_reason=FollowUpCancelReason.EXPECTED_DATE_CHANGED,
        )
        return FollowUpLifecycleResult(
            action=FollowUpLifecycleAction.RESCHEDULED,
            follow_up=replacement,
            previous_follow_up=active,
        )

    @staticmethod
    def _cancel_reason(state, expected_date):
        if state is RequirementState.SATISFIED:
            return FollowUpCancelReason.REQUIREMENT_SATISFIED
        if expected_date is None:
            return FollowUpCancelReason.EXPECTED_DATE_REMOVED
        return None

    def _audit(
        self,
        event_type: str,
        *,
        requirement,
        follow_up: FollowUp,
        originating_state_transition_id: UUID | None,
        originating_audit_event_id: UUID | None,
        correspondence_event_id: UUID | None,
        ai_proposal_id: UUID | None,
        policy_evaluation_id: UUID | None,
        actor_type: str,
        actor_identifier: str | None,
        previous_follow_up: FollowUp | None = None,
        cancellation_reason: FollowUpCancelReason | None = None,
    ) -> None:
        self.audit.create_audit_event(
            event_type=event_type,
            actor_type=actor_type,
            actor_identifier=actor_identifier,
            correspondence_event_id=correspondence_event_id,
            project_id=requirement.project_id,
            requirement_id=requirement.id,
            ai_proposal_id=ai_proposal_id,
            policy_evaluation_id=policy_evaluation_id,
            state_transition_id=originating_state_transition_id,
            details={
                "follow_up_id": str(follow_up.id),
                "project_id": str(requirement.project_id),
                "requirement_id": str(requirement.id),
                "purpose": follow_up.purpose.value,
                "expected_date": follow_up.expected_date.isoformat(),
                "due_on": follow_up.due_on.isoformat(),
                "previous_follow_up_id": (
                    str(previous_follow_up.id) if previous_follow_up else None
                ),
                "replacement_follow_up_id": (
                    str(follow_up.id) if previous_follow_up else None
                ),
                "cancellation_reason": (
                    cancellation_reason.value if cancellation_reason else None
                ),
                "originating_state_transition_id": (
                    str(originating_state_transition_id)
                    if originating_state_transition_id
                    else None
                ),
                "originating_audit_event_id": (
                    str(originating_audit_event_id)
                    if originating_audit_event_id
                    else None
                ),
            },
        )
