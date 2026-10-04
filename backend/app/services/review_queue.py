from uuid import UUID

from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewCorrespondence,
)
from app.contracts.review_queue import (
    PROJECT_RESOLUTION_ALLOWED_ACTIONS,
    NewRequirementReviewReadDetail,
    ProjectResolutionReviewReadDetail,
    RequirementChangeReviewReadDetail,
    ReviewQueueSummary,
    ReviewReadDetail,
)
from app.models.enums import ReviewStatus, ReviewType
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.policy.requirement_review_handoff import (
    RequirementReviewHandoffError,
    RequirementReviewHandoffService,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryError,
    ProjectResolutionReviewQueryService,
)

SUPPORTED_REVIEW_TYPES = {
    ReviewType.PROJECT_RESOLUTION,
    ReviewType.REQUIREMENT_CHANGE,
    ReviewType.NEW_REQUIREMENT,
}


class ReviewQueueNotFoundError(LookupError):
    pass


class ReviewQueueIntegrityError(RuntimeError):
    pass


class ReviewQueueQueryService:
    def __init__(
        self,
        *,
        review_repository: ReviewItemRepository,
        correspondence_repository: CorrespondenceEventRepository,
        project_resolution_query_service: ProjectResolutionReviewQueryService,
        requirement_handoff_service: RequirementReviewHandoffService,
    ) -> None:
        self.review_repository = review_repository
        self.correspondence_repository = correspondence_repository
        self.project_resolution_query_service = project_resolution_query_service
        self.requirement_handoff_service = requirement_handoff_service

    def list_pending(self) -> tuple[ReviewQueueSummary, ...]:
        return tuple(
            self._summary(review)
            for review in self.review_repository.list_pending(SUPPORTED_REVIEW_TYPES)
        )

    def get_detail(self, review_item_id: UUID) -> ReviewReadDetail:
        review = self.review_repository.get(review_item_id)
        if review is None or review.review_type not in SUPPORTED_REVIEW_TYPES:
            raise ReviewQueueNotFoundError("review item was not found")

        if review.review_type is ReviewType.PROJECT_RESOLUTION:
            try:
                detail = self.project_resolution_query_service.get_detail(
                    review_item_id
                )
            except ProjectResolutionReviewQueryError as exc:
                raise ReviewQueueIntegrityError(
                    "project-resolution review history is inconsistent"
                ) from exc
            return ProjectResolutionReviewReadDetail(
                allowed_actions=self._allowed_actions(review),
                detail=detail,
            )

        transition = self.review_repository.get_state_transition(
            review.state_transition_id
        )
        if transition is None:
            raise ReviewQueueIntegrityError(
                "requirement review transition is inconsistent"
            )
        try:
            handoff = self.requirement_handoff_service.load(
                transition.policy_evaluation_id
            )
        except RequirementReviewHandoffError as exc:
            raise ReviewQueueIntegrityError(
                "requirement review history is inconsistent"
            ) from exc
        if (
            handoff.state_transition_id != transition.id
            or handoff.correspondence_event_id != review.correspondence_event_id
        ):
            raise ReviewQueueIntegrityError(
                "requirement review history is inconsistent"
            )
        correspondence = self.correspondence_repository.get(
            review.correspondence_event_id
        )
        if correspondence is None:
            raise ReviewQueueIntegrityError(
                "requirement review correspondence is inconsistent"
            )
        correspondence_context = ProjectResolutionReviewCorrespondence(
            correspondence_event_id=correspondence.id,
            source=correspondence.source,
            sender_identifier=correspondence.sender_identifier,
            sender_email=correspondence.sender_email,
            sender_name=correspondence.sender_name,
            subject=correspondence.subject,
            body=correspondence.body,
            received_at=correspondence.received_at,
        )
        summary = self._summary(review)
        detail_type = (
            NewRequirementReviewReadDetail
            if review.review_type is ReviewType.NEW_REQUIREMENT
            else RequirementChangeReviewReadDetail
        )
        return detail_type(
            review=summary,
            correspondence=correspondence_context,
            handoff=handoff,
        )

    @classmethod
    def _summary(cls, review) -> ReviewQueueSummary:
        return ReviewQueueSummary(
            review_item_id=review.id,
            correspondence_event_id=review.correspondence_event_id,
            review_type=review.review_type,
            status=review.status,
            review_reason=review.review_reason,
            created_at=review.created_at,
            resolved_at=review.resolved_at,
            allowed_actions=cls._allowed_actions(review),
        )

    @staticmethod
    def _allowed_actions(review):
        if (
            review.status is ReviewStatus.PENDING
            and review.review_type is ReviewType.PROJECT_RESOLUTION
        ):
            return PROJECT_RESOLUTION_ALLOWED_ACTIONS
        return ()
