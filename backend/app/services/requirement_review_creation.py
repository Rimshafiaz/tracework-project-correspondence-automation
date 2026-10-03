from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.requirement_schemas import RequirementImpactDisposition
from app.contracts.requirement_review import RequirementReviewHandoff
from app.models.enums import PolicyDecision, ReviewType
from app.models.review_item import ReviewItem
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.policy.requirement_review_handoff import RequirementReviewHandoffService

REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT = "requirement_review_created"


class RequirementReviewCreationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequirementReviewCreationResult:
    review_item: ReviewItem
    handoff: RequirementReviewHandoff
    created: bool


class RequirementReviewCreationService:
    def __init__(
        self,
        *,
        session: Session,
        lineage_repository: LineageRepository,
        requirement_repository: RequirementRepository,
        review_repository: ReviewItemRepository,
    ) -> None:
        self.session = session
        self.lineage_repository = lineage_repository
        self.requirement_repository = requirement_repository
        self.review_repository = review_repository

    def ensure_review_for_policy_evaluation(
        self,
        policy_evaluation_id: UUID,
    ) -> RequirementReviewCreationResult:
        try:
            evaluation = (
                self.lineage_repository.get_policy_evaluation_by_id_for_update(
                    policy_evaluation_id
                )
            )
            if evaluation is None:
                raise RequirementReviewCreationError(
                    "requirement policy evaluation was not found"
                )
            if evaluation.decision is not PolicyDecision.REVIEW_REQUIRED:
                raise RequirementReviewCreationError(
                    "only review-required policy evaluations may enter the queue"
                )

            handoff = RequirementReviewHandoffService(
                lineage_repository=self.lineage_repository,
                requirement_repository=self.requirement_repository,
            ).load(policy_evaluation_id)
            review = self.review_repository.get_by_state_transition(
                handoff.state_transition_id
            )
            created = review is None
            if review is None:
                review = self.review_repository.create_requirement_review(
                    correspondence_event_id=handoff.correspondence_event_id,
                    state_transition_id=handoff.state_transition_id,
                    review_type=self._review_type(handoff),
                    review_reason=(
                        " ".join(handoff.transition_preview.policy.reasons)
                        or "Requirement changes require human review."
                    ),
                )

            if self.lineage_repository.get_audit_event(
                event_type=REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT,
                policy_evaluation_id=policy_evaluation_id,
                project_id=handoff.project_id,
            ) is None:
                self.lineage_repository.create_audit_event(
                    event_type=REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT,
                    actor_type="system",
                    correspondence_event_id=handoff.correspondence_event_id,
                    project_id=handoff.project_id,
                    ai_proposal_id=handoff.proposal_id,
                    policy_evaluation_id=policy_evaluation_id,
                    state_transition_id=handoff.state_transition_id,
                    review_item_id=review.id,
                    details={
                        "policy_version": handoff.transition_preview.policy.policy_version,
                        "triggered_rule_ids": list(
                            handoff.transition_preview.policy.triggered_rule_ids
                        ),
                        "review_type": review.review_type.value,
                    },
                )

            self.session.commit()
            return RequirementReviewCreationResult(
                review_item=review,
                handoff=handoff,
                created=created,
            )
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _review_type(handoff: RequirementReviewHandoff) -> ReviewType:
        has_existing_change = any(
            impact.disposition is RequirementImpactDisposition.UPDATE_PROPOSED
            for impact in handoff.reconciliation.existing_impacts
        )
        if handoff.reconciliation.new_requirements and not has_existing_change:
            return ReviewType.NEW_REQUIREMENT
        return ReviewType.REQUIREMENT_CHANGE
