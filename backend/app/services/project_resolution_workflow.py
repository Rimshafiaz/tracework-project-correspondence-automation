from dataclasses import dataclass
from uuid import UUID

from app.models.enums import PolicyDecision
from app.models.review_item import ReviewItem
from app.services.policy.project_identity_authorization import (
    ProjectIdentityAuthorizationResult,
    ProjectIdentityAuthorizationService,
)
from app.services.project_resolution_review_creation import (
    ProjectResolutionReviewCreationService,
)


@dataclass(frozen=True)
class ProjectResolutionWorkflowResult:
    authorization: ProjectIdentityAuthorizationResult
    review_item: ReviewItem | None


class ProjectResolutionWorkflowService:
    def __init__(
        self,
        *,
        authorization_service: ProjectIdentityAuthorizationService,
        review_creation_service: ProjectResolutionReviewCreationService,
    ) -> None:
        self.authorization_service = authorization_service
        self.review_creation_service = review_creation_service

    def process(self, proposal_id: UUID) -> ProjectResolutionWorkflowResult:
        authorization = self.authorization_service.authorize(proposal_id)
        review_item = None
        if authorization.evaluation.decision is PolicyDecision.REVIEW_REQUIRED:
            review_item = (
                self.review_creation_service.ensure_review_for_policy_evaluation(
                    authorization.evaluation.id
                ).review_item
            )
        return ProjectResolutionWorkflowResult(
            authorization=authorization,
            review_item=review_item,
        )
