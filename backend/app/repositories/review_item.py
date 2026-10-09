from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.project_resolution_review_queue import PROJECT_RESOLUTION_LINK_ENTITY_TYPE
from app.models.enums import ReviewStatus, ReviewType, TransitionStatus
from app.models.review_item import ReviewItem, ReviewItemCandidateProject
from app.models.state_transition import StateTransition


class ReviewItemStateError(ValueError):
    pass


class ReviewItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, review_item_id: UUID) -> ReviewItem | None:
        return self.session.get(ReviewItem, review_item_id)

    def get_for_update(self, review_item_id: UUID) -> ReviewItem | None:
        return self.session.scalar(
            select(ReviewItem)
            .where(ReviewItem.id == review_item_id)
            .with_for_update()
        )

    def list_pending_project_resolution(self) -> Sequence[ReviewItem]:
        return self.session.scalars(
            select(ReviewItem)
            .where(
                ReviewItem.review_type == ReviewType.PROJECT_RESOLUTION,
                ReviewItem.status == ReviewStatus.PENDING,
            )
            .order_by(ReviewItem.created_at, ReviewItem.id)
        ).all()

    def list_pending(
        self,
        review_types: set[ReviewType],
    ) -> Sequence[ReviewItem]:
        if not review_types:
            return []
        return self.session.scalars(
            select(ReviewItem)
            .where(
                ReviewItem.review_type.in_(review_types),
                ReviewItem.status == ReviewStatus.PENDING,
            )
            .order_by(ReviewItem.created_at, ReviewItem.id)
        ).all()

    def get_by_state_transition(
        self,
        state_transition_id: UUID,
    ) -> ReviewItem | None:
        return self.session.scalar(
            select(ReviewItem).where(
                ReviewItem.state_transition_id == state_transition_id
            )
        )

    def get_state_transition(
        self,
        state_transition_id: UUID,
    ) -> StateTransition | None:
        return self.session.get(StateTransition, state_transition_id)

    def get_project_resolution_transition(
        self,
        *,
        policy_evaluation_id: UUID,
        correspondence_event_id: UUID,
    ) -> StateTransition | None:
        return self.session.scalar(
            select(StateTransition).where(
                StateTransition.policy_evaluation_id == policy_evaluation_id,
                StateTransition.affected_entity_type
                == PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
                StateTransition.affected_entity_id == correspondence_event_id,
            )
        )

    def create_project_resolution_review(
        self,
        *,
        correspondence_event_id: UUID,
        state_transition_id: UUID,
        review_reason: str,
        candidate_project_ids: Sequence[UUID],
    ) -> ReviewItem:
        review_reason = review_reason.strip()
        if not review_reason:
            raise ValueError("review_reason must not be blank")
        candidate_project_ids = tuple(dict.fromkeys(candidate_project_ids))
        review = ReviewItem(
            correspondence_event_id=correspondence_event_id,
            state_transition_id=state_transition_id,
            review_type=ReviewType.PROJECT_RESOLUTION,
            review_reason=review_reason,
            status=ReviewStatus.PENDING,
            candidate_project_links=[
                ReviewItemCandidateProject(project_id=project_id)
                for project_id in candidate_project_ids
            ],
        )
        self.session.add(review)
        self.session.flush()
        return review

    def create_requirement_review(
        self,
        *,
        correspondence_event_id: UUID,
        state_transition_id: UUID,
        review_type: ReviewType,
        review_reason: str,
    ) -> ReviewItem:
        if review_type not in {
            ReviewType.REQUIREMENT_CHANGE,
            ReviewType.NEW_REQUIREMENT,
            ReviewType.RETRACTION_CORRECTION,
        }:
            raise ValueError("requirement review type is invalid")
        review_reason = review_reason.strip()
        if not review_reason:
            raise ValueError("review_reason must not be blank")
        review = ReviewItem(
            correspondence_event_id=correspondence_event_id,
            state_transition_id=state_transition_id,
            review_type=review_type,
            review_reason=review_reason,
            status=ReviewStatus.PENDING,
        )
        self.session.add(review)
        self.session.flush()
        return review

    def list_candidate_project_ids(self, review_item_id: UUID) -> Sequence[UUID]:
        return self.session.scalars(
            select(ReviewItemCandidateProject.project_id)
            .where(ReviewItemCandidateProject.review_item_id == review_item_id)
            .order_by(ReviewItemCandidateProject.project_id)
        ).all()

    def mark_approved(
        self,
        review: ReviewItem,
        *,
        resolved_at: datetime,
    ) -> ReviewItem:
        self._require_pending(review)
        self._require_timezone(resolved_at)
        review.status = ReviewStatus.APPROVED
        review.correction_payload = None
        review.resolved_at = resolved_at
        self.session.flush()
        return review

    def mark_corrected(
        self,
        review: ReviewItem,
        *,
        correction_payload: dict[str, object],
        resolved_at: datetime,
    ) -> ReviewItem:
        self._require_pending(review)
        self._require_timezone(resolved_at)
        if not correction_payload:
            raise ValueError("correction_payload must not be empty")
        review.status = ReviewStatus.CORRECTED
        review.correction_payload = correction_payload
        review.resolved_at = resolved_at
        self.session.flush()
        return review

    def mark_rejected(
        self,
        review: ReviewItem,
        *,
        resolved_at: datetime,
    ) -> ReviewItem:
        self._require_pending(review)
        self._require_timezone(resolved_at)
        review.status = ReviewStatus.REJECTED
        review.correction_payload = None
        review.resolved_at = resolved_at
        self.session.flush()
        return review

    def mark_transition_applied(
        self,
        transition: StateTransition,
        *,
        applied_at: datetime,
    ) -> StateTransition:
        self._require_previewed_transition(transition)
        self._require_timezone(applied_at)
        transition.status = TransitionStatus.APPLIED
        transition.applied_at = applied_at
        self.session.flush()
        return transition

    def mark_transition_superseded(
        self,
        transition: StateTransition,
    ) -> StateTransition:
        self._require_previewed_transition(transition)
        transition.status = TransitionStatus.SUPERSEDED
        transition.applied_at = None
        self.session.flush()
        return transition

    def mark_transition_rejected(
        self,
        transition: StateTransition,
    ) -> StateTransition:
        self._require_previewed_transition(transition)
        transition.status = TransitionStatus.REJECTED
        transition.applied_at = None
        self.session.flush()
        return transition

    @staticmethod
    def _require_pending(review: ReviewItem) -> None:
        if review.status is not ReviewStatus.PENDING:
            raise ReviewItemStateError("review item is already resolved")

    @staticmethod
    def _require_timezone(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("resolved_at must include a timezone")

    @staticmethod
    def _require_previewed_transition(transition: StateTransition) -> None:
        if transition.status is not TransitionStatus.PREVIEWED:
            raise ReviewItemStateError("review transition is already resolved")
