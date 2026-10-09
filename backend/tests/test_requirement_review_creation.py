from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.ai.requirement_schemas import NewRequirementProposal, RequirementCorrectionKind, RequirementCorrectionProposal, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.models.enums import PolicyDecision, RequirementState, ReviewStatus, ReviewType
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationResult
from app.services.requirement_policy_workflow import RequirementPolicyWorkflowService
from app.services.requirement_review_creation import REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT, RequirementReviewCreationError, RequirementReviewCreationService
from tests.test_requirement_review_handoff import FakeLineageRepository, FakeRequirementRepository


class CreationLineageRepository(FakeLineageRepository):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.audits = []
        self.lock_count = 0

    def get_policy_evaluation_by_id_for_update(self, evaluation_id):
        self.lock_count += 1
        return self.get_policy_evaluation_by_id(evaluation_id)

    def get_audit_event(self, *, event_type, policy_evaluation_id, project_id=None):
        return next(
            (
                item
                for item in self.audits
                if item.event_type == event_type
                and item.policy_evaluation_id == policy_evaluation_id
                and item.project_id == project_id
            ),
            None,
        )

    def create_audit_event(self, **values):
        audit = SimpleNamespace(id=uuid4(), **values)
        self.audits.append(audit)
        return audit


class FakeReviewRepository:
    def __init__(self):
        self.reviews = {}

    def get_by_state_transition(self, transition_id):
        return self.reviews.get(transition_id)

    def create_requirement_review(self, **values):
        review = SimpleNamespace(
            id=uuid4(),
            status=ReviewStatus.PENDING,
            **values,
        )
        self.reviews[values["state_transition_id"]] = review
        return review


def _service(lineage):
    session = MagicMock(spec=Session)
    reviews = FakeReviewRepository()
    service = RequirementReviewCreationService(
        session=session,
        lineage_repository=lineage,
        requirement_repository=FakeRequirementRepository(lineage),
        review_repository=reviews,
    )
    return service, session, reviews


@pytest.mark.parametrize(
    "new_requirement,expected_type",
    [
        (False, ReviewType.REQUIREMENT_CHANGE),
        (True, ReviewType.NEW_REQUIREMENT),
    ],
)
def test_creates_one_typed_requirement_review(new_requirement, expected_type) -> None:
    lineage = CreationLineageRepository(new_requirement=new_requirement)
    service, session, reviews = _service(lineage)

    first = service.ensure_review_for_policy_evaluation(lineage.evaluation.id)
    repeated = service.ensure_review_for_policy_evaluation(lineage.evaluation.id)

    assert first.created is True
    assert repeated.created is False
    assert first.review_item.review_type is expected_type
    assert len(reviews.reviews) == 1
    assert len(lineage.audits) == 1
    assert lineage.audits[0].event_type == REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT
    assert lineage.lock_count == 2
    assert session.commit.call_count == 2
    session.rollback.assert_not_called()


def test_non_review_policy_cannot_enter_requirement_queue() -> None:
    lineage = CreationLineageRepository(decision=PolicyDecision.ALLOW_AUTO_ACTION)
    service, session, reviews = _service(lineage)

    with pytest.raises(RequirementReviewCreationError, match="review-required"):
        service.ensure_review_for_policy_evaluation(lineage.evaluation.id)

    assert reviews.reviews == {}
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_correction_uses_existing_review_queue_with_distinct_type() -> None:
    lineage = CreationLineageRepository()
    reconciliation = RequirementReconciliation.model_validate(lineage.proposal.structured_output)
    impact = reconciliation.existing_impacts[0]
    lineage.proposal.structured_output = RequirementReconciliation(corrections=(
        RequirementCorrectionProposal(
            kind=RequirementCorrectionKind.RETRACTION,
            requirement_id=impact.requirement_id,
            previous_state=RequirementState.OPEN,
            target_evidence_item_ids=(lineage.evidence.id,),
            evidence=(impact.evidence[0],),
            interpretation="The earlier statement was withdrawn.",
        ),
    )).model_dump(mode="json")
    lineage.transition.requirement_effects = []
    service, _, _ = _service(lineage)

    result = service.ensure_review_for_policy_evaluation(lineage.evaluation.id)

    assert result.review_item.review_type is ReviewType.RETRACTION_CORRECTION
    assert result.review_item.status is ReviewStatus.PENDING


def test_mixed_existing_and_new_proposals_use_requirement_change_review() -> None:
    lineage = CreationLineageRepository()
    reconciliation = RequirementReconciliation.model_validate(
        lineage.proposal.structured_output
    )
    lineage.proposal.structured_output = reconciliation.model_copy(
        update={
            "new_requirements": (
                NewRequirementProposal(
                    name="Additional neutral obligation",
                    evidence=(
                        RequirementSourceEvidence(
                            correspondence_event_id=lineage.proposal.correspondence_event_id,
                            source_field=ResolverSourceField.BODY,
                            excerpt="review evidence",
                        ),
                    ),
                    interpretation="The correspondence also appears to add scope.",
                ),
            )
        }
    ).model_dump(mode="json")
    service, _, _ = _service(lineage)

    result = service.ensure_review_for_policy_evaluation(lineage.evaluation.id)

    assert result.review_item.review_type is ReviewType.REQUIREMENT_CHANGE


def test_workflow_repairs_interruption_after_authorization_commit() -> None:
    lineage = CreationLineageRepository()
    creation_service, _, reviews = _service(lineage)
    authorization_service = MagicMock()
    authorization_service.authorize.return_value = RequirementPolicyAuthorizationResult(
        evaluation=lineage.evaluation,
        transition=lineage.transition,
        policy_evaluation_created=False,
        transition_created=False,
        applied_requirement_ids=(),
    )
    workflow = RequirementPolicyWorkflowService(
        authorization_service=authorization_service,
        review_creation_service=creation_service,
    )

    authorization_service.authorize(lineage.proposal.id)
    assert reviews.reviews == {}

    recovered = workflow.process(lineage.proposal.id)
    repeated = workflow.process(lineage.proposal.id)

    assert recovered.review.created is True
    assert repeated.review.created is False
    assert len(reviews.reviews) == 1
    assert len(lineage.audits) == 1


def test_workflow_does_not_queue_auto_authorization() -> None:
    lineage = CreationLineageRepository(decision=PolicyDecision.ALLOW_AUTO_ACTION)
    authorization_service = MagicMock()
    authorization_service.authorize.return_value = RequirementPolicyAuthorizationResult(
        evaluation=lineage.evaluation,
        transition=None,
        policy_evaluation_created=False,
        transition_created=False,
        applied_requirement_ids=(),
    )
    review_creation_service = MagicMock()
    result = RequirementPolicyWorkflowService(
        authorization_service=authorization_service,
        review_creation_service=review_creation_service,
    ).process(lineage.proposal.id)

    assert result.review is None
    review_creation_service.ensure_review_for_policy_evaluation.assert_not_called()
