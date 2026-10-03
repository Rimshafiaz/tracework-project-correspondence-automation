from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.schemas import CandidateSignalReference, EvidenceConflict, ProjectResolution, ResolutionConcern, ResolutionEvidence, ResolutionStatus
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal, serialize_project_candidate_snapshot
from app.models.enums import EvidenceValidity, PolicyDecision, ProjectStatus, ProposalType
from app.services.policy import ProjectResolutionReviewHandoffError, ProjectResolutionReviewHandoffService


class FakeLineageRepository:
    def __init__(
        self,
        *,
        evaluation,
        proposal,
        proposal_evidence=(),
        policy_evidence=(),
        candidate_evidence=(),
    ) -> None:
        self.evaluation = evaluation
        self.proposal = proposal
        self.proposal_evidence = list(proposal_evidence)
        self.policy_evidence = list(policy_evidence)
        self.candidate_evidence = {
            item.id: item for item in candidate_evidence
        }

    def get_policy_evaluation_by_id(self, evaluation_id):
        return self.evaluation if self.evaluation.id == evaluation_id else None

    def get_proposal(self, proposal_id):
        return self.proposal if self.proposal.id == proposal_id else None

    def list_proposal_evidence(self, proposal_id):
        return self.proposal_evidence

    def list_policy_evidence(self, evaluation_id):
        return self.policy_evidence

    def list_evidence_by_ids(self, evidence_ids):
        return [
            self.candidate_evidence[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.candidate_evidence
        ]


def _candidate(name: str, *, evidence_item_id=None) -> ProjectCandidate:
    project_id = uuid4()
    return ProjectCandidate(
        project_id=project_id,
        project_code=f"CODE-{str(project_id)[:8]}",
        project_name=name,
        project_status=ProjectStatus.ACTIVE,
        signals=(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.NORMALIZED_NAME,
                matched_value=name.casefold(),
                source=(
                    CandidateSignalSource.EVIDENCE_ITEM
                    if evidence_item_id is not None
                    else CandidateSignalSource.CORRESPONDENCE_EVENT
                ),
                evidence_item_id=evidence_item_id,
                exact=True,
            ),
        ),
    )


def _reference(candidate: ProjectCandidate) -> CandidateSignalReference:
    signal = candidate.signals[0]
    return CandidateSignalReference(
        project_id=candidate.project_id,
        signal_type=signal.signal_type,
        matched_value=signal.matched_value,
        source=signal.source,
        evidence_item_id=signal.evidence_item_id,
    )


def _evaluation(proposal_id, *, decision=PolicyDecision.REVIEW_REQUIRED):
    return SimpleNamespace(
        id=uuid4(),
        ai_proposal_id=proposal_id,
        policy_version="project-identity/1",
        decision=decision,
        triggered_rule_ids=["PID-101-RESOLVER-REVIEW-REQUIRED"],
        reasons=["The resolver could not select a project without human review."],
    )


def test_review_handoff_reconstructs_candidates_resolution_policy_and_evidence() -> None:
    proposal_evidence = SimpleNamespace(id=uuid4(), validity=EvidenceValidity.VALID)
    invalid_candidate_evidence = SimpleNamespace(
        id=uuid4(),
        validity=EvidenceValidity.INVALIDATED,
    )
    first = _candidate("First")
    second = _candidate("Second")
    alternative = _candidate(
        "Alternative",
        evidence_item_id=invalid_candidate_evidence.id,
    )
    first_reference = _reference(first)
    second_reference = _reference(second)
    resolution = ProjectResolution(
        status=ResolutionStatus.REVIEW_REQUIRED,
        project_ids=(first.project_id, second.project_id),
        evidence=(
            ResolutionEvidence(
                project_id=first.project_id,
                signal_references=(first_reference,),
                interpretation="The first reference is plausible.",
            ),
            ResolutionEvidence(
                project_id=second.project_id,
                signal_references=(second_reference,),
                interpretation="The second reference is plausible.",
            ),
        ),
        conflicts=(
            EvidenceConflict(
                project_ids=(first.project_id, second.project_id),
                signal_references=(first_reference, second_reference),
                description="The references identify different projects.",
            ),
        ),
        concerns=(ResolutionConcern.AMBIGUOUS_CANDIDATES,),
    )
    proposal_id = uuid4()
    event_id = uuid4()
    candidates = ProjectCandidateSet(candidates=(first, second, alternative))
    proposal = SimpleNamespace(
        id=proposal_id,
        correspondence_event_id=event_id,
        proposal_type=ProposalType.PROJECT_RESOLUTION,
        input_metadata=serialize_project_candidate_snapshot(candidates),
        structured_output=resolution.model_dump(mode="json"),
    )
    evaluation = _evaluation(proposal_id)
    repository = FakeLineageRepository(
        evaluation=evaluation,
        proposal=proposal,
        proposal_evidence=(proposal_evidence,),
        policy_evidence=(proposal_evidence,),
        candidate_evidence=(invalid_candidate_evidence,),
    )

    handoff = ProjectResolutionReviewHandoffService(repository).load(
        evaluation.id
    )

    assert handoff.correspondence_event_id == event_id
    assert handoff.selected_project_ids == (first.project_id, second.project_id)
    assert handoff.alternative_project_ids == (alternative.project_id,)
    assert handoff.resolution.conflicts == resolution.conflicts
    assert handoff.resolution.concerns == resolution.concerns
    assert handoff.policy.policy_version == "project-identity/1"
    assert handoff.policy.triggered_rule_ids == tuple(evaluation.triggered_rule_ids)
    assert handoff.valid_evidence_ids == (proposal_evidence.id,)
    assert handoff.invalidated_evidence_ids == (invalid_candidate_evidence.id,)
    assert handoff.requires_manual_project_assignment is False


def test_no_match_handoff_supports_manual_assignment_without_project_or_evidence() -> None:
    proposal_id = uuid4()
    resolution = ProjectResolution(
        status=ResolutionStatus.NO_MATCH,
        concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
    )
    proposal = SimpleNamespace(
        id=proposal_id,
        correspondence_event_id=uuid4(),
        proposal_type=ProposalType.PROJECT_RESOLUTION,
        input_metadata=serialize_project_candidate_snapshot(ProjectCandidateSet()),
        structured_output=resolution.model_dump(mode="json"),
    )
    evaluation = _evaluation(proposal_id)
    repository = FakeLineageRepository(
        evaluation=evaluation,
        proposal=proposal,
    )

    handoff = ProjectResolutionReviewHandoffService(repository).load(
        evaluation.id
    )

    assert handoff.selected_project_ids == ()
    assert handoff.alternative_project_ids == ()
    assert handoff.valid_evidence_ids == ()
    assert handoff.invalidated_evidence_ids == ()
    assert handoff.requires_manual_project_assignment is True


def test_only_review_required_policy_has_a_review_handoff() -> None:
    proposal_id = uuid4()
    proposal = SimpleNamespace(
        id=proposal_id,
        correspondence_event_id=uuid4(),
        proposal_type=ProposalType.PROJECT_RESOLUTION,
        input_metadata={},
        structured_output={},
    )
    evaluation = _evaluation(
        proposal_id,
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
    )

    with pytest.raises(ProjectResolutionReviewHandoffError, match="review-required"):
        ProjectResolutionReviewHandoffService(
            FakeLineageRepository(
                evaluation=evaluation,
                proposal=proposal,
            )
        ).load(evaluation.id)


def test_missing_candidate_evidence_reference_is_rejected() -> None:
    missing_evidence_id = uuid4()
    candidate = _candidate("Example", evidence_item_id=missing_evidence_id)
    resolution = ProjectResolution(
        status=ResolutionStatus.REVIEW_REQUIRED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_reference(candidate),),
                interpretation="The candidate requires review.",
            ),
        ),
        concerns=(ResolutionConcern.INSUFFICIENT_EVIDENCE,),
    )
    proposal_id = uuid4()
    proposal = SimpleNamespace(
        id=proposal_id,
        correspondence_event_id=uuid4(),
        proposal_type=ProposalType.PROJECT_RESOLUTION,
        input_metadata=serialize_project_candidate_snapshot(
            ProjectCandidateSet(candidates=(candidate,))
        ),
        structured_output=resolution.model_dump(mode="json"),
    )
    evaluation = _evaluation(proposal_id)

    with pytest.raises(ProjectResolutionReviewHandoffError, match="was not found"):
        ProjectResolutionReviewHandoffService(
            FakeLineageRepository(
                evaluation=evaluation,
                proposal=proposal,
            )
        ).load(evaluation.id)
