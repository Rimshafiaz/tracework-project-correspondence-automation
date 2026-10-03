from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

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
from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewAction,
    ProjectResolutionReviewApproval,
    ProjectResolutionReviewDecisionContext,
    ProjectResolutionReviewReplacementAssignment,
    ReviewActor,
)
from app.models.enums import (
    PolicyDecision,
    ProjectStatus,
    ProposalType,
    ReviewStatus,
    ReviewType,
    TransitionStatus,
)
from app.services.project_resolution_review_decision import (
    ProjectResolutionReviewDecisionError,
    ProjectResolutionReviewDecisionService,
)


def _candidate(name: str) -> ProjectCandidate:
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
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                exact=True,
            ),
        ),
    )


def _resolution(
    status: ResolutionStatus,
    candidates: tuple[ProjectCandidate, ...],
) -> ProjectResolution:
    if status is ResolutionStatus.NO_MATCH:
        return ProjectResolution(
            status=status,
            concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
        )
    return ProjectResolution(
        status=status,
        project_ids=tuple(item.project_id for item in candidates),
        evidence=tuple(
            ResolutionEvidence(
                project_id=item.project_id,
                signal_references=(
                    CandidateSignalReference(
                        project_id=item.project_id,
                        signal_type=item.signals[0].signal_type,
                        matched_value=item.signals[0].matched_value,
                        source=item.signals[0].source,
                    ),
                ),
                interpretation="The correspondence plausibly refers to this project.",
            )
            for item in candidates
        ),
        concerns=(ResolutionConcern.AMBIGUOUS_CANDIDATES,),
    )


class DecisionFixture:
    def __init__(
        self,
        status: ResolutionStatus = ResolutionStatus.REVIEW_REQUIRED,
        *,
        selected_count: int = 1,
    ) -> None:
        self.selected = tuple(
            _candidate(f"Selected {index}") for index in range(selected_count)
        )
        candidates = () if status is ResolutionStatus.NO_MATCH else self.selected
        self.resolution = _resolution(status, candidates)
        self.event_id = uuid4()
        self.proposal = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=self.event_id,
            proposal_type=ProposalType.PROJECT_RESOLUTION,
            input_metadata=serialize_project_candidate_snapshot(
                ProjectCandidateSet(candidates=candidates)
            ),
            structured_output=self.resolution.model_dump(mode="json"),
        )
        self.evaluation = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_version="project-identity/1",
            decision=PolicyDecision.REVIEW_REQUIRED,
            triggered_rule_ids=["PID-101-RESOLVER-REVIEW-REQUIRED"],
            reasons=["Human review is required."],
        )
        self.transition = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_evaluation_id=self.evaluation.id,
            affected_entity_type="correspondence_project_links",
            affected_entity_id=self.event_id,
            status=TransitionStatus.PREVIEWED,
            applied_at=None,
        )
        self.review = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=self.event_id,
            state_transition_id=self.transition.id,
            review_type=ReviewType.PROJECT_RESOLUTION,
            status=ReviewStatus.PENDING,
            correction_payload=None,
            resolved_at=None,
        )
        self.projects = {
            item.project_id: SimpleNamespace(id=item.project_id)
            for item in self.selected
        }
        self.links = {}
        self.audits = []
        self.session = MagicMock(spec=Session)
        self.review_repository = SimpleNamespace(
            get_for_update=lambda review_id: (
                self.review if review_id == self.review.id else None
            ),
            get_state_transition=lambda transition_id: (
                self.transition if transition_id == self.transition.id else None
            ),
            mark_transition_applied=self._mark_transition_applied,
            mark_transition_superseded=self._mark_transition_superseded,
            mark_transition_rejected=self._mark_transition_rejected,
            mark_approved=self._mark_approved,
            mark_corrected=self._mark_corrected,
            mark_rejected=self._mark_rejected,
        )
        self.lineage_repository = SimpleNamespace(
            get_policy_evaluation_by_id=lambda evaluation_id: (
                self.evaluation
                if evaluation_id == self.evaluation.id
                else None
            ),
            get_proposal=lambda proposal_id: (
                self.proposal if proposal_id == self.proposal.id else None
            ),
            list_proposal_evidence=lambda proposal_id: [],
            list_policy_evidence=lambda evaluation_id: [],
            list_evidence_by_ids=lambda evidence_ids: [],
            create_audit_event=self._create_audit,
        )
        self.project_repository = SimpleNamespace(
            get=lambda project_id: self.projects.get(project_id)
        )
        self.project_link_repository = SimpleNamespace(
            get_or_create_approved_link=self._get_or_create_link,
            get_approved_link=self._get_link,
        )
        self.fail_on_project_id = None

    def service(self):
        return ProjectResolutionReviewDecisionService(
            session=self.session,
            review_repository=self.review_repository,
            lineage_repository=self.lineage_repository,
            project_repository=self.project_repository,
            project_link_repository=self.project_link_repository,
        )

    def add_project(self):
        project_id = uuid4()
        self.projects[project_id] = SimpleNamespace(id=project_id)
        return project_id

    def _get_or_create_link(self, *, correspondence_event_id, project_id):
        if project_id == self.fail_on_project_id:
            raise RuntimeError("link creation failed")
        key = (correspondence_event_id, project_id)
        if key in self.links:
            return self.links[key], False
        link = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=correspondence_event_id,
            project_id=project_id,
        )
        self.links[key] = link
        return link, True

    def _get_link(self, *, correspondence_event_id, project_id):
        return self.links.get((correspondence_event_id, project_id))

    def _create_audit(self, **values):
        audit = SimpleNamespace(id=uuid4(), **values)
        self.audits.append(audit)
        return audit

    def _mark_transition_applied(self, transition, *, applied_at):
        transition.status = TransitionStatus.APPLIED
        transition.applied_at = applied_at

    def _mark_transition_superseded(self, transition):
        transition.status = TransitionStatus.SUPERSEDED

    def _mark_transition_rejected(self, transition):
        transition.status = TransitionStatus.REJECTED

    def _mark_approved(self, review, *, resolved_at):
        review.status = ReviewStatus.APPROVED
        review.resolved_at = resolved_at

    def _mark_corrected(self, review, *, correction_payload, resolved_at):
        review.status = ReviewStatus.CORRECTED
        review.correction_payload = correction_payload
        review.resolved_at = resolved_at

    def _mark_rejected(self, review, *, resolved_at):
        review.status = ReviewStatus.REJECTED
        review.resolved_at = resolved_at


ACTOR = ReviewActor(
    actor_type="operator_supplied",
    actor_identifier="reviewer@example.test",
)


def test_approval_uses_exact_m8_project_set_and_preserves_history() -> None:
    fixture = DecisionFixture()
    proposal_before = deepcopy(fixture.proposal.structured_output)
    evaluation_before = deepcopy(fixture.evaluation.__dict__)

    result = fixture.service().approve(
        fixture.review.id,
        ProjectResolutionReviewApproval(actor=ACTOR, comment="Approved."),
    )

    assert result.action is ProjectResolutionReviewAction.APPROVE_PROPOSAL
    assert tuple(link.project_id for link in result.project_links) == (
        fixture.selected[0].project_id,
    )
    assert fixture.review.status is ReviewStatus.APPROVED
    assert fixture.transition.status is TransitionStatus.APPLIED
    assert fixture.audits[0].actor_type == "operator_supplied"
    assert fixture.audits[0].details["authorization"] == "HUMAN_REVIEW"
    assert fixture.proposal.structured_output == proposal_before
    assert fixture.evaluation.__dict__ == evaluation_before
    fixture.session.commit.assert_called_once_with()


def test_correction_uses_replacement_set_and_supersedes_m8_preview() -> None:
    fixture = DecisionFixture()
    replacement_id = fixture.add_project()

    result = fixture.service().assign_or_correct(
        fixture.review.id,
        ProjectResolutionReviewReplacementAssignment(
            actor=ACTOR,
            project_ids=(replacement_id,),
        ),
    )

    assert result.action is ProjectResolutionReviewAction.CORRECT_PROJECTS
    assert fixture.review.status is ReviewStatus.CORRECTED
    assert fixture.transition.status is TransitionStatus.SUPERSEDED
    assert fixture.review.correction_payload["selected_project_ids"] == [
        str(replacement_id)
    ]


def test_correction_cannot_be_used_to_approve_the_proposed_set() -> None:
    fixture = DecisionFixture()

    with pytest.raises(ProjectResolutionReviewDecisionError, match="use approval"):
        fixture.service().assign_or_correct(
            fixture.review.id,
            ProjectResolutionReviewReplacementAssignment(
                actor=ACTOR,
                project_ids=(fixture.selected[0].project_id,),
            ),
        )

    assert fixture.review.status is ReviewStatus.PENDING
    assert fixture.links == {}


def test_no_match_supports_manual_assignment_but_not_approval() -> None:
    fixture = DecisionFixture(ResolutionStatus.NO_MATCH, selected_count=0)
    assigned_id = fixture.add_project()

    with pytest.raises(ProjectResolutionReviewDecisionError, match="manual"):
        fixture.service().approve(
            fixture.review.id,
            ProjectResolutionReviewApproval(actor=ACTOR),
        )

    result = fixture.service().assign_or_correct(
        fixture.review.id,
        ProjectResolutionReviewReplacementAssignment(
            actor=ACTOR,
            project_ids=(assigned_id,),
        ),
    )

    assert result.action is ProjectResolutionReviewAction.MANUAL_ASSIGNMENT
    assert fixture.review.status is ReviewStatus.CORRECTED


def test_rejection_creates_no_project_link() -> None:
    fixture = DecisionFixture()

    result = fixture.service().reject(
        fixture.review.id,
        ProjectResolutionReviewDecisionContext(actor=ACTOR),
    )

    assert result.action is ProjectResolutionReviewAction.REJECT
    assert result.project_links == ()
    assert fixture.links == {}
    assert fixture.review.status is ReviewStatus.REJECTED
    assert fixture.transition.status is TransitionStatus.REJECTED


def test_multi_project_approval_creates_the_complete_set_atomically() -> None:
    fixture = DecisionFixture(ResolutionStatus.MULTI_PROJECT, selected_count=2)

    result = fixture.service().approve(
        fixture.review.id,
        ProjectResolutionReviewApproval(actor=ACTOR),
    )

    assert {link.project_id for link in result.project_links} == {
        item.project_id for item in fixture.selected
    }
    assert len(result.created_project_link_ids) == 2
    fixture.session.commit.assert_called_once_with()


def test_missing_replacement_project_rolls_back_without_resolution() -> None:
    fixture = DecisionFixture()

    with pytest.raises(ProjectResolutionReviewDecisionError, match="do not exist"):
        fixture.service().assign_or_correct(
            fixture.review.id,
            ProjectResolutionReviewReplacementAssignment(
                actor=ACTOR,
                project_ids=(uuid4(),),
            ),
        )

    assert fixture.review.status is ReviewStatus.PENDING
    assert fixture.audits == []
    fixture.session.commit.assert_not_called()
    fixture.session.rollback.assert_called_once_with()


def test_exact_retry_returns_existing_result_without_duplicate_side_effects() -> None:
    fixture = DecisionFixture()
    decision = ProjectResolutionReviewApproval(actor=ACTOR)

    first = fixture.service().approve(fixture.review.id, decision)
    repeated = fixture.service().approve(fixture.review.id, decision)

    assert first.idempotent_replay is False
    assert repeated.idempotent_replay is True
    assert repeated.created_project_link_ids == ()
    assert len(fixture.links) == 1
    assert len(fixture.audits) == 1


def test_conflicting_second_decision_is_rejected() -> None:
    fixture = DecisionFixture()
    fixture.service().reject(
        fixture.review.id,
        ProjectResolutionReviewDecisionContext(actor=ACTOR),
    )

    with pytest.raises(ProjectResolutionReviewDecisionError, match="differently"):
        fixture.service().approve(
            fixture.review.id,
            ProjectResolutionReviewApproval(actor=ACTOR),
        )


def test_link_failure_rolls_back_whole_decision() -> None:
    fixture = DecisionFixture(ResolutionStatus.MULTI_PROJECT, selected_count=2)
    fixture.fail_on_project_id = fixture.selected[1].project_id

    with pytest.raises(RuntimeError, match="link creation failed"):
        fixture.service().approve(
            fixture.review.id,
            ProjectResolutionReviewApproval(actor=ACTOR),
        )

    assert fixture.review.status is ReviewStatus.PENDING
    assert fixture.audits == []
    fixture.session.commit.assert_not_called()
    fixture.session.rollback.assert_called_once_with()
