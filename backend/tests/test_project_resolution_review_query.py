from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.schemas import (
    CandidateSignalReference,
    ProjectResolution,
    ResolutionConcern,
    ResolutionEvidence,
    ResolutionStatus,
)
from app.contracts.project_candidate import (
    CandidateSignalSource,
    CandidateSignalType,
    ProjectCandidate,
    ProjectCandidateSet,
    ProjectCandidateSignal,
    serialize_project_candidate_snapshot,
)
from app.models.enums import (
    EvidenceValidity,
    PolicyDecision,
    ProjectStatus,
    ProposalType,
    ReviewStatus,
    ReviewType,
    TransitionDisposition,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryError,
    ProjectResolutionReviewQueryService,
)


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


class QueryFixture:
    def __init__(self, *, no_match: bool = False) -> None:
        now = datetime.now(UTC)
        self.event = SimpleNamespace(
            id=uuid4(),
            source="gmail",
            sender_identifier="sender@example.test",
            sender_email="sender@example.test",
            sender_name="Sender",
            subject="Project question",
            body="Please confirm the project.",
            received_at=now,
        )
        self.valid_evidence = SimpleNamespace(
            id=uuid4(),
            attachment_id=None,
            source_type="correspondence_body",
            page_number=None,
            section=None,
            excerpt="Please confirm the project.",
            validity=EvidenceValidity.VALID,
            invalidation_reason=None,
        )
        self.invalidated_evidence = SimpleNamespace(
            id=uuid4(),
            attachment_id=uuid4(),
            source_type="attachment_text",
            page_number=1,
            section=None,
            excerpt="An outdated project reference.",
            validity=EvidenceValidity.INVALIDATED,
            invalidation_reason="The sender withdrew the attachment.",
        )
        if no_match:
            candidates = ProjectCandidateSet()
            resolution = ProjectResolution(
                status=ResolutionStatus.NO_MATCH,
                concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
            )
            proposal_evidence = ()
            candidate_evidence = ()
        else:
            selected = _candidate("Selected")
            alternative = _candidate(
                "Alternative",
                evidence_item_id=self.invalidated_evidence.id,
            )
            candidates = ProjectCandidateSet(
                candidates=(selected, alternative)
            )
            resolution = ProjectResolution(
                status=ResolutionStatus.REVIEW_REQUIRED,
                project_ids=(selected.project_id,),
                evidence=(
                    ResolutionEvidence(
                        project_id=selected.project_id,
                        signal_references=(_reference(selected),),
                        interpretation="The message plausibly names this project.",
                    ),
                ),
                concerns=(ResolutionConcern.AMBIGUOUS_CANDIDATES,),
            )
            proposal_evidence = (self.valid_evidence,)
            candidate_evidence = (self.invalidated_evidence,)
        self.candidates = candidates
        self.resolution = resolution
        self.proposal = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=self.event.id,
            proposal_type=ProposalType.PROJECT_RESOLUTION,
            input_metadata=serialize_project_candidate_snapshot(candidates),
            structured_output=resolution.model_dump(mode="json"),
        )
        self.evaluation = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_version="project-identity/1",
            decision=PolicyDecision.REVIEW_REQUIRED,
            triggered_rule_ids=["PID-101-RESOLVER-REVIEW-REQUIRED"],
            reasons=["The project identity needs human review."],
        )
        self.transition = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_evaluation_id=self.evaluation.id,
            affected_entity_type="correspondence_project_links",
            affected_entity_id=self.event.id,
            current_state={"project_ids": []},
            proposed_state={
                "project_ids": [str(item) for item in resolution.project_ids],
                "resolver_status": resolution.status.value,
                "requires_manual_project_assignment": no_match,
            },
            disposition=TransitionDisposition.REVIEW,
        )
        self.review = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=self.event.id,
            state_transition_id=self.transition.id,
            review_type=ReviewType.PROJECT_RESOLUTION,
            review_reason="The project identity needs human review.",
            status=ReviewStatus.PENDING,
            created_at=now,
            resolved_at=None,
        )
        self.proposal_evidence = proposal_evidence
        self.candidate_evidence = candidate_evidence
        self.transition_evidence = (
            *proposal_evidence,
            *candidate_evidence,
        )

    def service(self):
        return ProjectResolutionReviewQueryService(
            review_repository=SimpleNamespace(
                list_pending_project_resolution=lambda: [self.review],
                get=lambda review_id: (
                    self.review if review_id == self.review.id else None
                ),
                get_state_transition=lambda transition_id: (
                    self.transition
                    if transition_id == self.transition.id
                    else None
                ),
            ),
            correspondence_repository=SimpleNamespace(
                get=lambda event_id: self.event if event_id == self.event.id else None
            ),
            lineage_repository=SimpleNamespace(
                get_policy_evaluation_by_id=lambda evaluation_id: (
                    self.evaluation
                    if evaluation_id == self.evaluation.id
                    else None
                ),
                get_proposal=lambda proposal_id: (
                    self.proposal if proposal_id == self.proposal.id else None
                ),
                list_proposal_evidence=lambda proposal_id: list(
                    self.proposal_evidence
                ),
                list_policy_evidence=lambda evaluation_id: [],
                list_evidence_by_ids=lambda evidence_ids: [
                    item
                    for item in self.candidate_evidence
                    if item.id in evidence_ids
                ],
                list_state_transition_evidence=lambda transition_id: list(
                    self.transition_evidence
                ),
            ),
        )


def test_list_open_returns_small_review_summaries() -> None:
    fixture = QueryFixture()

    summaries = fixture.service().list_open()

    assert len(summaries) == 1
    assert summaries[0].review_item_id == fixture.review.id
    assert summaries[0].review_reason == fixture.review.review_reason


def test_detail_reconstructs_correspondence_interpretation_policy_and_evidence() -> None:
    fixture = QueryFixture()

    detail = fixture.service().get_detail(fixture.review.id)

    assert detail.correspondence.body == fixture.event.body
    assert detail.candidate_set == fixture.candidates
    assert detail.resolution == fixture.resolution
    assert detail.preview.proposed_project_ids == fixture.resolution.project_ids
    assert detail.preview.policy.reasons == tuple(fixture.evaluation.reasons)
    assert {item.validity for item in detail.evidence} == {
        EvidenceValidity.VALID,
        EvidenceValidity.INVALIDATED,
    }
    assert detail.evidence[1].invalidation_reason is not None


def test_no_match_detail_requires_manual_assignment_without_fake_project() -> None:
    fixture = QueryFixture(no_match=True)

    detail = fixture.service().get_detail(fixture.review.id)

    assert detail.preview.proposed_project_ids == ()
    assert detail.preview.requires_manual_project_assignment is True
    assert detail.evidence == ()


def test_detail_rejects_preview_that_no_longer_matches_handoff() -> None:
    fixture = QueryFixture()
    fixture.transition.proposed_state["project_ids"] = [str(uuid4())]

    with pytest.raises(ProjectResolutionReviewQueryError, match="preview is invalid"):
        fixture.service().get_detail(fixture.review.id)
