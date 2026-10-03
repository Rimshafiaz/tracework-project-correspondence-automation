from uuid import UUID

from pydantic import ValidationError

from app.ai.schemas import ProjectResolution
from app.contracts.project_candidate import reconstruct_project_candidate_snapshot
from app.contracts.project_resolution_review import ProjectResolutionReviewHandoff
from app.contracts.transition_preview import PolicyEvaluationSnapshot
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType
from app.repositories.lineage import LineageRepository


class ProjectResolutionReviewHandoffError(RuntimeError):
    pass


class ProjectResolutionReviewHandoffService:
    def __init__(self, repository: LineageRepository) -> None:
        self.repository = repository

    def load(
        self,
        policy_evaluation_id: UUID,
    ) -> ProjectResolutionReviewHandoff:
        evaluation = self.repository.get_policy_evaluation_by_id(
            policy_evaluation_id
        )
        if evaluation is None:
            raise ProjectResolutionReviewHandoffError(
                "project identity policy evaluation was not found"
            )
        if evaluation.decision is not PolicyDecision.REVIEW_REQUIRED:
            raise ProjectResolutionReviewHandoffError(
                "only review-required policy evaluations have a review handoff"
            )

        proposal = self.repository.get_proposal(evaluation.ai_proposal_id)
        if proposal is None or proposal.proposal_type is not ProposalType.PROJECT_RESOLUTION:
            raise ProjectResolutionReviewHandoffError(
                "project-resolution proposal was not found"
            )
        try:
            resolution = ProjectResolution.model_validate(proposal.structured_output)
            candidate_set = reconstruct_project_candidate_snapshot(
                proposal.input_metadata
            )
        except (ValidationError, ValueError) as exc:
            raise ProjectResolutionReviewHandoffError(
                "persisted project-resolution review data is invalid"
            ) from exc

        proposal_evidence = self.repository.list_proposal_evidence(proposal.id)
        policy_evidence = self.repository.list_policy_evidence(evaluation.id)
        candidate_evidence_ids = tuple(
            dict.fromkeys(
                signal.evidence_item_id
                for candidate in candidate_set.candidates
                for signal in candidate.signals
                if signal.evidence_item_id is not None
            )
        )
        candidate_evidence = self.repository.list_evidence_by_ids(
            set(candidate_evidence_ids)
        )
        evidence_by_id = {
            item.id: item
            for item in (*proposal_evidence, *policy_evidence, *candidate_evidence)
        }
        referenced_ids = set(
            (
                *(item.id for item in proposal_evidence),
                *(item.id for item in policy_evidence),
                *candidate_evidence_ids,
            )
        )
        if referenced_ids != set(evidence_by_id):
            raise ProjectResolutionReviewHandoffError(
                "review evidence reference was not found"
            )

        return ProjectResolutionReviewHandoff(
            correspondence_event_id=proposal.correspondence_event_id,
            proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            candidate_set=candidate_set,
            resolution=resolution,
            policy=PolicyEvaluationSnapshot(
                id=evaluation.id,
                policy_version=evaluation.policy_version,
                decision=evaluation.decision,
                triggered_rule_ids=tuple(evaluation.triggered_rule_ids),
                reasons=tuple(evaluation.reasons),
            ),
            proposal_evidence_ids=tuple(item.id for item in proposal_evidence),
            policy_evidence_ids=tuple(item.id for item in policy_evidence),
            candidate_evidence_ids=candidate_evidence_ids,
            valid_evidence_ids=tuple(
                evidence_id
                for evidence_id, item in evidence_by_id.items()
                if item.validity is EvidenceValidity.VALID
            ),
            invalidated_evidence_ids=tuple(
                evidence_id
                for evidence_id, item in evidence_by_id.items()
                if item.validity is EvidenceValidity.INVALIDATED
            ),
        )
