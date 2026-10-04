from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from app.contracts.evidence_lineage import (
    CurrentRequirementState,
    EvidenceLineage,
    LineageAttachment,
    LineageAttribution,
    LineageAuditEvent,
    LineageCompleteness,
    LineageCorrespondence,
    LineageCurrentState,
    LineageEvidence,
    LineageOutcome,
    LineagePolicy,
    LineageProposal,
    LineageReview,
    LineageTransition,
)
from app.contracts.requirement_policy import RequirementTransitionEffect
from app.models.enums import EvidenceValidity, ReviewStatus, TransitionDisposition, TransitionStatus
from app.models.evidence_item import EvidenceItem
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository


class EvidenceLineageError(RuntimeError):
    pass


class EvidenceLineageService:
    def __init__(
        self,
        *,
        lineage_repository: LineageRepository,
        correspondence_repository: CorrespondenceEventRepository,
        attachment_repository: AttachmentRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
        requirement_repository: RequirementRepository,
        review_repository: ReviewItemRepository,
    ) -> None:
        self.lineage_repository = lineage_repository
        self.correspondence_repository = correspondence_repository
        self.attachment_repository = attachment_repository
        self.project_link_repository = project_link_repository
        self.requirement_repository = requirement_repository
        self.review_repository = review_repository

    def load(self, state_transition_id: UUID) -> EvidenceLineage:
        transition = self.lineage_repository.get_state_transition_by_id(
            state_transition_id
        )
        if transition is None:
            raise EvidenceLineageError("state transition was not found")
        proposal = self.lineage_repository.get_proposal(transition.ai_proposal_id)
        evaluation = self.lineage_repository.get_policy_evaluation_by_id(
            transition.policy_evaluation_id
        )
        if proposal is None or evaluation is None:
            raise EvidenceLineageError("transition proposal or policy was not found")
        if evaluation.ai_proposal_id != proposal.id:
            raise EvidenceLineageError("transition lineage is inconsistent")
        correspondence = self.correspondence_repository.get(
            proposal.correspondence_event_id
        )
        if correspondence is None:
            raise EvidenceLineageError("source correspondence was not found")

        review = self.review_repository.get_by_state_transition(transition.id)
        audit_events = tuple(
            self.lineage_repository.list_audit_events_for_lineage(
                ai_proposal_id=proposal.id,
                policy_evaluation_id=evaluation.id,
                state_transition_id=transition.id,
                review_item_id=review.id if review else None,
            )
        )
        outcome_at = review.resolved_at if review else transition.applied_at
        evidence = self._evidence(
            proposal_id=proposal.id,
            evaluation_id=evaluation.id,
            transition_id=transition.id,
            proposal_at=proposal.created_at,
            policy_at=evaluation.evaluated_at,
            outcome_at=outcome_at,
        )
        attachments = {
            item.id: item
            for item in self.attachment_repository.list_for_correspondence_event(
                correspondence.id
            )
        }
        missing_attachments = {
            item.attachment_id
            for item in evidence
            if item.attachment_id is not None and item.attachment_id not in attachments
        }
        if missing_attachments:
            raise EvidenceLineageError("referenced evidence attachment was not found")

        requirement_effects = self._requirement_effects(
            transition.requirement_effects
        )
        human_audit = next(
            (item for item in reversed(audit_events) if item.actor_type != "system"),
            None,
        )
        completeness_notes = () if audit_events else (
            "No linked audit events were persisted for this historical transition.",
        )
        return EvidenceLineage(
            completeness=(
                LineageCompleteness.COMPLETE
                if not completeness_notes
                else LineageCompleteness.LEGACY_PARTIAL
            ),
            completeness_notes=completeness_notes,
            correspondence=LineageCorrespondence(
                id=correspondence.id,
                source=correspondence.source,
                sender_identifier=correspondence.sender_identifier,
                subject=correspondence.subject,
                body=correspondence.body,
                received_at=correspondence.received_at,
            ),
            attachments=tuple(
                LineageAttachment(
                    id=item.id,
                    filename=item.filename,
                    mime_type=item.mime_type,
                    content_hash=item.content_hash,
                )
                for item in attachments.values()
                if item.id in {evidence_item.attachment_id for evidence_item in evidence}
            ),
            evidence=evidence,
            proposal=LineageProposal(
                id=proposal.id,
                proposal_type=proposal.proposal_type,
                model_identifier=proposal.model_identifier,
                prompt_version=proposal.prompt_version,
                input_hash=proposal.input_hash,
                structured_output=proposal.structured_output,
                created_at=proposal.created_at,
            ),
            policy=LineagePolicy(
                id=evaluation.id,
                policy_version=evaluation.policy_version,
                decision=evaluation.decision,
                triggered_rule_ids=tuple(evaluation.triggered_rule_ids),
                reasons=tuple(evaluation.reasons),
                evaluated_at=evaluation.evaluated_at,
            ),
            transition=LineageTransition(
                id=transition.id,
                affected_entity_type=transition.affected_entity_type,
                affected_entity_id=transition.affected_entity_id,
                historical_current_state=transition.current_state,
                historical_proposed_state=transition.proposed_state,
                requirement_effects=requirement_effects,
                disposition=transition.disposition,
                status=transition.status,
                created_at=transition.created_at,
                applied_at=transition.applied_at,
            ),
            review=(
                LineageReview(
                    id=review.id,
                    review_type=review.review_type,
                    status=review.status,
                    review_reason=review.review_reason,
                    correction_payload=review.correction_payload,
                    created_at=review.created_at,
                    resolved_at=review.resolved_at,
                )
                if review
                else None
            ),
            audit_events=tuple(
                LineageAuditEvent(
                    id=item.id,
                    event_type=item.event_type,
                    actor_type=item.actor_type,
                    authenticated_operator_subject=(
                        item.actor_identifier
                        if item.actor_type == "authenticated_operator"
                        else None
                    ),
                    operator_supplied_actor_label=(
                        item.actor_identifier
                        if item.actor_type == "operator_supplied"
                        else None
                    ),
                    details=item.details,
                    occurred_at=item.occurred_at,
                )
                for item in audit_events
            ),
            historical_outcome=LineageOutcome(
                attribution=self._attribution(transition, review),
                occurred_at=outcome_at,
                authenticated_operator_subject=(
                    human_audit.actor_identifier
                    if human_audit
                    and human_audit.actor_type == "authenticated_operator"
                    else None
                ),
                operator_supplied_actor_label=(
                    human_audit.actor_identifier
                    if human_audit
                    and human_audit.actor_type == "operator_supplied"
                    else None
                ),
            ),
            current_state=LineageCurrentState(
                linked_project_ids=tuple(
                    self.project_link_repository.list_approved_project_ids_for_event(
                        correspondence.id
                    )
                ),
                requirements=tuple(
                    self._current_requirement(effect.requirement_id)
                    for effect in requirement_effects
                ),
            ),
        )

    def _evidence(
        self,
        *,
        proposal_id: UUID,
        evaluation_id: UUID,
        transition_id: UUID,
        proposal_at: datetime,
        policy_at: datetime,
        outcome_at: datetime | None,
    ) -> tuple[LineageEvidence, ...]:
        proposal_evidence = tuple(
            self.lineage_repository.list_proposal_evidence(proposal_id)
        )
        policy_evidence = tuple(
            self.lineage_repository.list_policy_evidence(evaluation_id)
        )
        transition_evidence = tuple(
            self.lineage_repository.list_state_transition_evidence(transition_id)
        )
        proposal_ids = {item.id for item in proposal_evidence}
        policy_ids = {item.id for item in policy_evidence}
        transition_ids = {item.id for item in transition_evidence}
        evidence_by_id = {
            item.id: item
            for item in (*proposal_evidence, *policy_evidence, *transition_evidence)
        }
        return tuple(
            self._evidence_item(
                item,
                proposal_at=proposal_at,
                policy_at=policy_at,
                outcome_at=outcome_at,
                linked_to_proposal=item.id in proposal_ids,
                linked_to_policy=item.id in policy_ids,
                linked_to_transition=item.id in transition_ids,
            )
            for item in evidence_by_id.values()
        )

    @staticmethod
    def _evidence_item(
        item: EvidenceItem,
        *,
        proposal_at: datetime,
        policy_at: datetime,
        outcome_at: datetime | None,
        linked_to_proposal: bool,
        linked_to_policy: bool,
        linked_to_transition: bool,
    ) -> LineageEvidence:
        metadata = item.provenance_metadata or {}
        start_offset = metadata.get("start_offset")
        end_offset = metadata.get("end_offset")
        if not isinstance(start_offset, int):
            start_offset = None
        if not isinstance(end_offset, int):
            end_offset = None
        return LineageEvidence(
            id=item.id,
            correspondence_event_id=item.correspondence_event_id,
            attachment_id=item.attachment_id,
            project_id=item.project_id,
            requirement_id=item.requirement_id,
            source_type=item.source_type,
            excerpt=item.excerpt,
            start_offset=start_offset,
            end_offset=end_offset,
            page_number=item.page_number,
            section=item.section,
            validity_at_proposal=EvidenceLineageService._validity_at(
                item, proposal_at
            ),
            validity_at_policy=EvidenceLineageService._validity_at(item, policy_at),
            validity_at_outcome=(
                EvidenceLineageService._validity_at(item, outcome_at)
                if outcome_at
                else None
            ),
            current_validity=item.validity,
            invalidated_at=item.invalidated_at,
            invalidation_reason=item.invalidation_reason,
            linked_to_proposal=linked_to_proposal,
            linked_to_policy=linked_to_policy,
            linked_to_transition=linked_to_transition,
        )

    @staticmethod
    def _validity_at(item: EvidenceItem, at: datetime) -> EvidenceValidity:
        if item.invalidated_at is not None and item.invalidated_at <= at:
            return EvidenceValidity.INVALIDATED
        return EvidenceValidity.VALID

    @staticmethod
    def _requirement_effects(
        raw_effects: list[dict[str, object]],
    ) -> tuple[RequirementTransitionEffect, ...]:
        try:
            return tuple(
                RequirementTransitionEffect.model_validate(item)
                for item in raw_effects
            )
        except ValidationError as exc:
            raise EvidenceLineageError(
                "persisted requirement transition effects are invalid"
            ) from exc

    def _current_requirement(self, requirement_id: UUID) -> CurrentRequirementState:
        requirement = self.requirement_repository.get(requirement_id)
        if requirement is None:
            return CurrentRequirementState(
                requirement_id=requirement_id,
                exists=False,
                project_id=None,
                state=None,
                expected_date=None,
            )
        return CurrentRequirementState(
            requirement_id=requirement.id,
            exists=True,
            project_id=requirement.project_id,
            state=requirement.state,
            expected_date=requirement.expected_date,
        )

    @staticmethod
    def _attribution(transition, review) -> LineageAttribution:
        if review is not None and review.status is not ReviewStatus.PENDING:
            return LineageAttribution.HUMAN
        if (
            transition.disposition is TransitionDisposition.AUTO_APPLY
            and transition.status is TransitionStatus.APPLIED
        ):
            return LineageAttribution.AUTOMATIC
        return LineageAttribution.NONE
