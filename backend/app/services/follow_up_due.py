from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import FollowUpStatus
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository

FOLLOW_UP_BECAME_DUE_AUDIT_EVENT = "follow_up_became_due"


@dataclass(frozen=True)
class FollowUpDueProcessingResult:
    promoted_follow_up_ids: tuple[UUID, ...]

    @property
    def promoted_count(self) -> int:
        return len(self.promoted_follow_up_ids)


class FollowUpDueService:
    def __init__(
        self,
        *,
        session: Session,
        follow_up_repository: FollowUpRepository,
        audit_repository: LineageRepository,
    ) -> None:
        if any(
            repository.session is not session
            for repository in (follow_up_repository, audit_repository)
        ):
            raise ValueError("follow-up due repositories must share one session")
        self.session = session
        self.follow_ups = follow_up_repository
        self.audit = audit_repository

    def process_due(self) -> FollowUpDueProcessingResult:
        rows = self.follow_ups.claim_scheduled_due()
        if not rows:
            return FollowUpDueProcessingResult(promoted_follow_up_ids=())

        became_due_at = self.session.scalar(select(func.now()))
        if not isinstance(became_due_at, datetime):
            raise RuntimeError("database did not provide a due timestamp")

        promoted_ids = []
        for follow_up in rows:
            # The locking query only selects SCHEDULED rows. Keep an explicit
            # guard so the application boundary remains safe if a fake or
            # alternate repository implementation returns stale rows.
            if follow_up.status is not FollowUpStatus.SCHEDULED:
                continue
            previous_status = follow_up.status
            self.follow_ups.mark_due(follow_up, became_due_at=became_due_at)
            self.session.flush([follow_up])
            self.audit.create_audit_event(
                event_type=FOLLOW_UP_BECAME_DUE_AUDIT_EVENT,
                actor_type="system",
                correspondence_event_id=None,
                project_id=follow_up.project_id,
                requirement_id=follow_up.requirement_id,
                state_transition_id=follow_up.originating_state_transition_id,
                details={
                    "follow_up_id": str(follow_up.id),
                    "project_id": str(follow_up.project_id),
                    "requirement_id": str(follow_up.requirement_id),
                    "purpose": follow_up.purpose.value,
                    "expected_date": follow_up.expected_date.isoformat(),
                    "due_on": follow_up.due_on.isoformat(),
                    "became_due_at": became_due_at.isoformat(),
                    "originating_state_transition_id": (
                        str(follow_up.originating_state_transition_id)
                        if follow_up.originating_state_transition_id
                        else None
                    ),
                    "originating_audit_event_id": (
                        str(follow_up.originating_audit_event_id)
                        if follow_up.originating_audit_event_id
                        else None
                    ),
                    "previous_status": previous_status.value,
                    "new_status": FollowUpStatus.DUE.value,
                },
            )
            promoted_ids.append(follow_up.id)

        return FollowUpDueProcessingResult(
            promoted_follow_up_ids=tuple(promoted_ids)
        )
