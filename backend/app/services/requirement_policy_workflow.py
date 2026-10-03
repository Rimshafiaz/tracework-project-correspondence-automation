from dataclasses import dataclass
from uuid import UUID

from app.models.enums import PolicyDecision
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationResult, RequirementPolicyAuthorizationService
from app.services.requirement_review_creation import RequirementReviewCreationResult, RequirementReviewCreationService


@dataclass(frozen=True)
class RequirementPolicyWorkflowResult:
    authorization: RequirementPolicyAuthorizationResult
    review: RequirementReviewCreationResult | None


class RequirementPolicyWorkflowService:
    def __init__(
        self,
        *,
        authorization_service: RequirementPolicyAuthorizationService,
        review_creation_service: RequirementReviewCreationService,
    ) -> None:
        self.authorization_service = authorization_service
        self.review_creation_service = review_creation_service

    def process(self, proposal_id: UUID) -> RequirementPolicyWorkflowResult:
        authorization = self.authorization_service.authorize(proposal_id)
        review = (
            self.review_creation_service.ensure_review_for_policy_evaluation(
                authorization.evaluation.id
            )
            if authorization.evaluation.decision is PolicyDecision.REVIEW_REQUIRED
            else None
        )
        return RequirementPolicyWorkflowResult(
            authorization=authorization,
            review=review,
        )
