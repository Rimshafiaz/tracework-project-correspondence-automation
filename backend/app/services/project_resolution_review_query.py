from uuid import UUID

from pydantic import ValidationError

from app.ai.schemas import ResolutionStatus
from app.contracts.project_resolution_review_queue import (
    PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
    ProjectResolutionReviewCorrespondence,
    ProjectResolutionReviewDetail,
    ProjectResolutionReviewEvidence,
    ProjectResolutionReviewPreview,
    ProjectResolutionReviewSummary,
)
from app.models.enums import ReviewType
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.lineage import LineageRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.policy.project_resolution_review_handoff import (
    ProjectResolutionReviewHandoffError,
    ProjectResolutionReviewHandoffService,
)


class ProjectResolutionReviewQueryError(RuntimeError):
    pass


class ProjectResolutionReviewQueryService:
    def __init__(
        self,
        *,
        review_repository: ReviewItemRepository,
        correspondence_repository: CorrespondenceEventRepository,
        lineage_repository: LineageRepository,
    ) -> None:
        self.review_repository = review_repository
        self.correspondence_repository = correspondence_repository
        self.lineage_repository = lineage_repository

    def list_open(self) -> tuple[ProjectResolutionReviewSummary, ...]:
        return tuple(
            self._summary(review)
            for review in self.review_repository.list_pending_project_resolution()
        )

    def get_detail(self, review_item_id: UUID) -> ProjectResolutionReviewDetail:
        review = self.review_repository.get(review_item_id)
        if review is None or review.review_type is not ReviewType.PROJECT_RESOLUTION:
            raise ProjectResolutionReviewQueryError(
                "project-resolution review item was not found"
            )
        transition = self.review_repository.get_state_transition(
            review.state_transition_id
        )
        if transition is None:
            raise ProjectResolutionReviewQueryError(
                "project-resolution review transition was not found"
            )
        if (
            transition.affected_entity_type
            != PROJECT_RESOLUTION_LINK_ENTITY_TYPE
            or transition.affected_entity_id != review.correspondence_event_id
        ):
            raise ProjectResolutionReviewQueryError(
                "project-resolution review transition is inconsistent"
            )

        try:
            handoff = ProjectResolutionReviewHandoffService(
                self.lineage_repository
            ).load(transition.policy_evaluation_id)
        except ProjectResolutionReviewHandoffError as exc:
            raise ProjectResolutionReviewQueryError(
                "project-resolution review lineage is invalid"
            ) from exc
        if (
            handoff.correspondence_event_id != review.correspondence_event_id
            or handoff.proposal_id != transition.ai_proposal_id
        ):
            raise ProjectResolutionReviewQueryError(
                "project-resolution review lineage is inconsistent"
            )
        correspondence = self.correspondence_repository.get(
            review.correspondence_event_id
        )
        if correspondence is None:
            raise ProjectResolutionReviewQueryError(
                "review correspondence was not found"
            )

        evidence = self.lineage_repository.list_state_transition_evidence(
            transition.id
        )
        evidence_ids = tuple(item.id for item in evidence)
        expected_evidence_ids = (
            *handoff.valid_evidence_ids,
            *handoff.invalidated_evidence_ids,
        )
        if set(evidence_ids) != set(expected_evidence_ids):
            raise ProjectResolutionReviewQueryError(
                "project-resolution review evidence is inconsistent"
            )
        try:
            preview = self._persisted_preview(transition, handoff)
            return ProjectResolutionReviewDetail(
                review=self._summary(review),
                state_transition_id=transition.id,
                proposal_id=handoff.proposal_id,
                policy_evaluation_id=handoff.policy_evaluation_id,
                correspondence=ProjectResolutionReviewCorrespondence(
                    correspondence_event_id=correspondence.id,
                    source=correspondence.source,
                    sender_identifier=correspondence.sender_identifier,
                    sender_email=correspondence.sender_email,
                    sender_name=correspondence.sender_name,
                    subject=correspondence.subject,
                    body=correspondence.body,
                    received_at=correspondence.received_at,
                ),
                preview=preview,
                candidate_set=handoff.candidate_set,
                resolution=handoff.resolution,
                evidence=tuple(
                    ProjectResolutionReviewEvidence(
                        evidence_item_id=item.id,
                        attachment_id=item.attachment_id,
                        source_type=item.source_type,
                        page_number=item.page_number,
                        section=item.section,
                        excerpt=item.excerpt,
                        validity=item.validity,
                        invalidation_reason=item.invalidation_reason,
                    )
                    for item in evidence
                ),
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ProjectResolutionReviewQueryError(
                "persisted project-resolution review preview is invalid"
            ) from exc

    @staticmethod
    def _summary(review) -> ProjectResolutionReviewSummary:
        return ProjectResolutionReviewSummary(
            review_item_id=review.id,
            correspondence_event_id=review.correspondence_event_id,
            status=review.status,
            review_reason=review.review_reason,
            created_at=review.created_at,
            resolved_at=review.resolved_at,
        )

    @staticmethod
    def _persisted_preview(transition, handoff) -> ProjectResolutionReviewPreview:
        current_project_ids = tuple(
            UUID(value) for value in transition.current_state["project_ids"]
        )
        proposed_project_ids = tuple(
            UUID(value) for value in transition.proposed_state["project_ids"]
        )
        resolver_status = ResolutionStatus(
            transition.proposed_state["resolver_status"]
        )
        manual_assignment = transition.proposed_state[
            "requires_manual_project_assignment"
        ]
        if (
            proposed_project_ids != handoff.selected_project_ids
            or resolver_status is not handoff.resolution.status
            or manual_assignment is not handoff.requires_manual_project_assignment
        ):
            raise ValueError("persisted preview does not match the M8/M9 handoff")
        return ProjectResolutionReviewPreview(
            correspondence_event_id=handoff.correspondence_event_id,
            resolver_status=resolver_status,
            current_project_ids=current_project_ids,
            proposed_project_ids=proposed_project_ids,
            alternative_project_ids=handoff.alternative_project_ids,
            valid_evidence_ids=handoff.valid_evidence_ids,
            invalidated_evidence_ids=handoff.invalidated_evidence_ids,
            policy=handoff.policy,
            disposition=transition.disposition,
            requires_manual_project_assignment=manual_assignment,
        )
