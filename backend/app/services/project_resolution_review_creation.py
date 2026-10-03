from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.project_resolution_review_queue import (
    PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
    ProjectResolutionReviewPreview,
)
from app.models.enums import PolicyDecision
from app.models.review_item import ReviewItem
from app.repositories.correspondence_project_link import (
    CorrespondenceProjectLinkRepository,
)
from app.repositories.lineage import LineageRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.policy.project_resolution_review_handoff import (
    ProjectResolutionReviewHandoffService,
)
from app.services.project_resolution_review_preview import (
    build_project_resolution_review_preview,
)

REVIEW_CREATED_AUDIT_EVENT = "project_resolution_review_created"


class ProjectResolutionReviewCreationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectResolutionReviewCreationResult:
    review_item: ReviewItem
    preview: ProjectResolutionReviewPreview
    created: bool


class ProjectResolutionReviewCreationService:
    def __init__(
        self,
        *,
        session: Session,
        lineage_repository: LineageRepository,
        review_repository: ReviewItemRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
    ) -> None:
        self.session = session
        self.lineage_repository = lineage_repository
        self.review_repository = review_repository
        self.project_link_repository = project_link_repository

    def ensure_review_for_policy_evaluation(
        self,
        policy_evaluation_id: UUID,
    ) -> ProjectResolutionReviewCreationResult:
        try:
            evaluation = (
                self.lineage_repository.get_policy_evaluation_by_id_for_update(
                    policy_evaluation_id
                )
            )
            if evaluation is None:
                raise ProjectResolutionReviewCreationError(
                    "project identity policy evaluation was not found"
                )
            if evaluation.decision is not PolicyDecision.REVIEW_REQUIRED:
                raise ProjectResolutionReviewCreationError(
                    "only review-required policy evaluations may enter the queue"
                )

            handoff = ProjectResolutionReviewHandoffService(
                self.lineage_repository
            ).load(policy_evaluation_id)
            preview = build_project_resolution_review_preview(
                handoff=handoff,
                current_project_ids=(
                    self.project_link_repository.list_approved_project_ids_for_event(
                        handoff.correspondence_event_id
                    )
                ),
            )
            transition = self.review_repository.get_project_resolution_transition(
                policy_evaluation_id=policy_evaluation_id,
                correspondence_event_id=handoff.correspondence_event_id,
            )
            if transition is None:
                transition = self.lineage_repository.create_transition(
                    ai_proposal_id=handoff.proposal_id,
                    policy_evaluation_id=policy_evaluation_id,
                    affected_entity_type=PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
                    affected_entity_id=handoff.correspondence_event_id,
                    current_state={
                        "project_ids": [
                            str(project_id)
                            for project_id in preview.current_project_ids
                        ]
                    },
                    proposed_state={
                        "project_ids": [
                            str(project_id)
                            for project_id in preview.proposed_project_ids
                        ],
                        "resolver_status": preview.resolver_status.value,
                        "requires_manual_project_assignment": (
                            preview.requires_manual_project_assignment
                        ),
                    },
                    requirement_effects=[],
                    document_effects=[],
                    follow_up_effects=[],
                    disposition=preview.disposition,
                    evidence_item_ids=(
                        *preview.valid_evidence_ids,
                        *preview.invalidated_evidence_ids,
                    ),
                )

            review = self.review_repository.get_by_state_transition(transition.id)
            created = review is None
            if review is None:
                review = self.review_repository.create_project_resolution_review(
                    correspondence_event_id=handoff.correspondence_event_id,
                    state_transition_id=transition.id,
                    review_reason=(
                        " ".join(handoff.policy.reasons)
                        or "Project identity requires human review."
                    ),
                    candidate_project_ids=tuple(
                        candidate.project_id
                        for candidate in handoff.candidate_set.candidates
                    ),
                )

            if self.lineage_repository.get_audit_event(
                event_type=REVIEW_CREATED_AUDIT_EVENT,
                policy_evaluation_id=policy_evaluation_id,
            ) is None:
                self.lineage_repository.create_audit_event(
                    event_type=REVIEW_CREATED_AUDIT_EVENT,
                    actor_type="system",
                    correspondence_event_id=handoff.correspondence_event_id,
                    ai_proposal_id=handoff.proposal_id,
                    policy_evaluation_id=policy_evaluation_id,
                    state_transition_id=transition.id,
                    review_item_id=review.id,
                    details={
                        "policy_version": handoff.policy.policy_version,
                        "triggered_rule_ids": list(
                            handoff.policy.triggered_rule_ids
                        ),
                        "resolver_status": handoff.resolution.status.value,
                    },
                )

            self.session.commit()
            return ProjectResolutionReviewCreationResult(
                review_item=review,
                preview=preview,
                created=created,
            )
        except Exception:
            self.session.rollback()
            raise
