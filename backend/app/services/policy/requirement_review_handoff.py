from uuid import UUID

from pydantic import ValidationError

from app.ai.requirement_schemas import RequirementReconciliation
from app.contracts.requirement_policy import RequirementCurrentRecord, RequirementPolicyTransitionPreview, RequirementTransitionEffect
from app.contracts.requirement_reconciliation import reconstruct_requirement_context_snapshot
from app.contracts.requirement_review import RequirementReviewEvidence, RequirementReviewHandoff
from app.contracts.transition_preview import PolicyEvaluationSnapshot, TransitionState
from app.models.enums import PolicyDecision, ProposalType, TransitionDisposition
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.services.policy.requirement_persistence import REQUIREMENT_RECONCILIATION_ENTITY_TYPE


class RequirementReviewHandoffError(RuntimeError):
    pass


class RequirementReviewHandoffService:
    def __init__(
        self,
        *,
        lineage_repository: LineageRepository,
        requirement_repository: RequirementRepository,
    ) -> None:
        self.lineage_repository = lineage_repository
        self.requirement_repository = requirement_repository

    def load(self, policy_evaluation_id: UUID) -> RequirementReviewHandoff:
        evaluation = self.lineage_repository.get_policy_evaluation_by_id(
            policy_evaluation_id
        )
        if evaluation is None or evaluation.decision is not PolicyDecision.REVIEW_REQUIRED:
            raise RequirementReviewHandoffError(
                "review-required requirement policy evaluation was not found"
            )
        proposal = self.lineage_repository.get_proposal(evaluation.ai_proposal_id)
        if (
            proposal is None
            or proposal.proposal_type is not ProposalType.REQUIREMENT_RECONCILIATION
        ):
            raise RequirementReviewHandoffError(
                "requirement-reconciliation proposal was not found"
            )
        transition = self.lineage_repository.get_state_transition(
            policy_evaluation_id=evaluation.id,
            affected_entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
            affected_entity_id=proposal.id,
        )
        if transition is None or transition.disposition is not TransitionDisposition.REVIEW:
            raise RequirementReviewHandoffError(
                "requirement review transition was not found"
            )

        try:
            reconciliation = RequirementReconciliation.model_validate(
                proposal.structured_output
            )
            snapshot = reconstruct_requirement_context_snapshot(
                proposal.input_metadata
            )
            effects = tuple(
                RequirementTransitionEffect.model_validate(item)
                for item in transition.requirement_effects
            )
            policy = PolicyEvaluationSnapshot(
                id=evaluation.id,
                policy_version=evaluation.policy_version,
                decision=evaluation.decision,
                triggered_rule_ids=tuple(evaluation.triggered_rule_ids),
                reasons=tuple(evaluation.reasons),
            )
            transition_evidence = tuple(
                self.lineage_repository.list_state_transition_evidence(
                    transition.id
                )
            )
            referenced_evidence = (
                *transition_evidence,
                *self.lineage_repository.list_proposal_evidence(proposal.id),
                *self.lineage_repository.list_policy_evidence(evaluation.id),
                *self.lineage_repository.list_evidence_by_ids(
                    {
                        item.evidence_item_id
                        for item in snapshot.existing_evidence
                    }
                ),
            )
            evidence_by_id = {
                item.id: item for item in referenced_evidence
            }
            evidence = tuple(
                RequirementReviewEvidence(
                    evidence_item_id=item.id,
                    attachment_id=item.attachment_id,
                    requirement_id=item.requirement_id,
                    source_type=item.source_type,
                    page_number=item.page_number,
                    section=item.section,
                    excerpt=item.excerpt,
                    validity=item.validity,
                    invalidation_reason=item.invalidation_reason,
                )
                for item in evidence_by_id.values()
            )
            preview = RequirementPolicyTransitionPreview(
                current_state=TransitionState(
                    entity_type=transition.affected_entity_type,
                    entity_id=transition.affected_entity_id,
                    values=transition.current_state,
                ),
                proposed_state=TransitionState(
                    entity_type=transition.affected_entity_type,
                    entity_id=transition.affected_entity_id,
                    values=transition.proposed_state,
                ),
                evidence_ids=tuple(item.id for item in transition_evidence),
                policy=policy,
                requirement_effects=effects,
                disposition=transition.disposition,
            )
            current_requirements = tuple(
                RequirementCurrentRecord(
                    requirement_id=item.id,
                    project_id=item.project_id,
                    name=item.name,
                    description=item.description,
                    state=item.state,
                    expected_date=item.expected_date,
                )
                for item in self.requirement_repository.list_for_project(
                    snapshot.project_id
                )
            )
            return RequirementReviewHandoff(
                correspondence_event_id=proposal.correspondence_event_id,
                proposal_id=proposal.id,
                policy_evaluation_id=evaluation.id,
                state_transition_id=transition.id,
                project_id=snapshot.project_id,
                reconciliation=reconciliation,
                m11_snapshot=snapshot,
                current_requirements=current_requirements,
                transition_preview=preview,
                evidence=evidence,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise RequirementReviewHandoffError(
                "persisted requirement review lineage is invalid"
            ) from exc
