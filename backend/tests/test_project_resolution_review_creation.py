from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.ai.schemas import ProjectResolution, ResolutionConcern, ResolutionStatus
from app.contracts.project_candidate import (
    ProjectCandidateSet,
    serialize_project_candidate_snapshot,
)
from app.models.enums import PolicyDecision, ProposalType, ReviewStatus, ReviewType
from app.services.policy.project_identity_authorization import (
    ProjectIdentityAuthorizationResult,
)
from app.services.project_resolution_review_creation import (
    REVIEW_CREATED_AUDIT_EVENT,
    ProjectResolutionReviewCreationError,
    ProjectResolutionReviewCreationService,
)
from app.services.project_resolution_workflow import (
    ProjectResolutionWorkflowService,
)


class FakeLineageRepository:
    def __init__(self, *, decision=PolicyDecision.REVIEW_REQUIRED) -> None:
        self.proposal = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=uuid4(),
            proposal_type=ProposalType.PROJECT_RESOLUTION,
            input_metadata=serialize_project_candidate_snapshot(
                ProjectCandidateSet()
            ),
            structured_output=ProjectResolution(
                status=ResolutionStatus.NO_MATCH,
                concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
            ).model_dump(mode="json"),
        )
        self.evaluation = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_version="project-identity/1",
            decision=decision,
            triggered_rule_ids=["PID-100-NO-MATCH"],
            reasons=["No plausible project was identified."],
        )
        self.transitions = []
        self.audits = []
        self.lock_count = 0

    def get_policy_evaluation_by_id_for_update(self, evaluation_id):
        self.lock_count += 1
        return self.evaluation if evaluation_id == self.evaluation.id else None

    def get_policy_evaluation_by_id(self, evaluation_id):
        return self.evaluation if evaluation_id == self.evaluation.id else None

    def get_proposal(self, proposal_id):
        return self.proposal if proposal_id == self.proposal.id else None

    def list_proposal_evidence(self, proposal_id):
        return []

    def list_policy_evidence(self, evaluation_id):
        return []

    def list_evidence_by_ids(self, evidence_ids):
        return []

    def create_transition(self, **values):
        transition = SimpleNamespace(id=uuid4(), **values)
        self.transitions.append(transition)
        return transition

    def get_audit_event(self, *, event_type, policy_evaluation_id, project_id=None):
        return next(
            (
                audit
                for audit in self.audits
                if audit.event_type == event_type
                and audit.policy_evaluation_id == policy_evaluation_id
            ),
            None,
        )

    def create_audit_event(self, **values):
        audit = SimpleNamespace(id=uuid4(), **values)
        self.audits.append(audit)
        return audit


class FakeReviewRepository:
    def __init__(self, lineage: FakeLineageRepository) -> None:
        self.lineage = lineage
        self.reviews = {}

    def get_project_resolution_transition(
        self,
        *,
        policy_evaluation_id,
        correspondence_event_id,
    ):
        return next(
            (
                transition
                for transition in self.lineage.transitions
                if transition.policy_evaluation_id == policy_evaluation_id
                and transition.affected_entity_id == correspondence_event_id
            ),
            None,
        )

    def get_by_state_transition(self, state_transition_id):
        return self.reviews.get(state_transition_id)

    def create_project_resolution_review(self, **values):
        review = SimpleNamespace(
            id=uuid4(),
            review_type=ReviewType.PROJECT_RESOLUTION,
            status=ReviewStatus.PENDING,
            **values,
        )
        self.reviews[values["state_transition_id"]] = review
        return review


class FakeProjectLinkRepository:
    def list_approved_project_ids_for_event(self, correspondence_event_id):
        return []


def _creation_service(lineage):
    session = MagicMock(spec=Session)
    reviews = FakeReviewRepository(lineage)
    service = ProjectResolutionReviewCreationService(
        session=session,
        lineage_repository=lineage,
        review_repository=reviews,
        project_link_repository=FakeProjectLinkRepository(),
    )
    return service, session, reviews


def _authorization_result(lineage):
    return ProjectIdentityAuthorizationResult(
        evaluation=lineage.evaluation,
        project_links=(),
        policy_evaluation_created=False,
        created_project_link_ids=(),
    )


def test_review_creation_persists_preview_review_and_audit_once() -> None:
    lineage = FakeLineageRepository()
    service, session, reviews = _creation_service(lineage)

    first = service.ensure_review_for_policy_evaluation(lineage.evaluation.id)
    repeated = service.ensure_review_for_policy_evaluation(lineage.evaluation.id)

    assert first.created is True
    assert repeated.created is False
    assert repeated.review_item is first.review_item
    assert first.preview.requires_manual_project_assignment is True
    assert first.preview.proposed_project_ids == ()
    assert len(lineage.transitions) == 1
    assert len(reviews.reviews) == 1
    assert len(lineage.audits) == 1
    assert lineage.audits[0].event_type == REVIEW_CREATED_AUDIT_EVENT
    assert lineage.lock_count == 2
    assert session.commit.call_count == 2
    session.rollback.assert_not_called()


def test_non_review_evaluation_cannot_enter_queue() -> None:
    lineage = FakeLineageRepository(decision=PolicyDecision.ALLOW_AUTO_ACTION)
    service, session, reviews = _creation_service(lineage)

    with pytest.raises(ProjectResolutionReviewCreationError, match="review-required"):
        service.ensure_review_for_policy_evaluation(lineage.evaluation.id)

    assert reviews.reviews == {}
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_normal_workflow_repairs_interruption_after_m9_commit() -> None:
    lineage = FakeLineageRepository()
    creation_service, _, reviews = _creation_service(lineage)
    authorization_service = MagicMock()
    authorization_service.authorize.return_value = _authorization_result(lineage)
    workflow = ProjectResolutionWorkflowService(
        authorization_service=authorization_service,
        review_creation_service=creation_service,
    )

    authorization_service.authorize(lineage.proposal.id)
    assert reviews.reviews == {}

    recovered = workflow.process(lineage.proposal.id)
    repeated = workflow.process(lineage.proposal.id)

    assert recovered.review_item is not None
    assert repeated.review_item is recovered.review_item
    assert len(lineage.transitions) == 1
    assert len(reviews.reviews) == 1
    assert len(lineage.audits) == 1


def test_normal_workflow_does_not_queue_automatic_decision() -> None:
    lineage = FakeLineageRepository(decision=PolicyDecision.ALLOW_AUTO_ACTION)
    authorization_service = MagicMock()
    authorization_service.authorize.return_value = _authorization_result(lineage)
    review_creation_service = MagicMock()
    workflow = ProjectResolutionWorkflowService(
        authorization_service=authorization_service,
        review_creation_service=review_creation_service,
    )

    result = workflow.process(lineage.proposal.id)

    assert result.review_item is None
    review_creation_service.ensure_review_for_policy_evaluation.assert_not_called()
