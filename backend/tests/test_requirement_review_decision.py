from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.requirement_review_decision import RequirementReviewAction
from app.models.enums import PolicyDecision, ReviewStatus, ReviewType, TransitionDisposition, TransitionStatus
from app.services.requirement_review_decision import (
    REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT,
    REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT,
    RequirementReviewDecisionError,
    RequirementReviewDecisionService,
)


class _Reviews:
    def __init__(self, review):
        self.review = review

    def get_for_update(self, review_id):
        return self.review if review_id == self.review.id else None

    def mark_approved(self, review, *, resolved_at):
        review.status = ReviewStatus.APPROVED
        review.resolved_at = resolved_at

    def mark_rejected(self, review, *, resolved_at):
        review.status = ReviewStatus.REJECTED
        review.resolved_at = resolved_at


class _Requirements:
    def __init__(self):
        self.created = []

    def get_for_update(self, requirement_id):
        return None

    def apply_authorized_change(self, requirement, **_values):
        return requirement

    def create(self, **values):
        item = SimpleNamespace(id=uuid4(), **values)
        self.created.append(item)
        return item


def _service():
    project_id = uuid4()
    correspondence_id = uuid4()
    proposal_id = uuid4()
    evaluation_id = uuid4()
    transition_id = uuid4()
    review = SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=correspondence_id,
        state_transition_id=transition_id,
        review_type=ReviewType.NEW_REQUIREMENT,
        status=ReviewStatus.PENDING,
        resolved_at=None,
    )
    proposal = SimpleNamespace(id=proposal_id, correspondence_event_id=correspondence_id)
    evaluation = SimpleNamespace(
        id=evaluation_id,
        ai_proposal_id=proposal_id,
        decision=PolicyDecision.REVIEW_REQUIRED,
        policy_version="requirement-policy/1",
    )
    transition = SimpleNamespace(
        id=transition_id,
        ai_proposal_id=proposal_id,
        policy_evaluation_id=evaluation_id,
        affected_entity_type="requirement_reconciliation",
        affected_entity_id=proposal_id,
        disposition=TransitionDisposition.REVIEW,
        status=TransitionStatus.PREVIEWED,
        current_state={"project_id": str(project_id)},
        requirement_effects=[],
    )
    lineage = MagicMock()
    lineage.get_state_transition_by_id_for_update.return_value = transition
    lineage.get_policy_evaluation_by_id_for_update.return_value = evaluation
    lineage.get_proposal_for_update.return_value = proposal
    lineage.list_policy_evidence.return_value = [SimpleNamespace(id=uuid4())]
    requirements = _Requirements()
    context = MagicMock()
    context.build.return_value = SimpleNamespace(
        m11_snapshot=SimpleNamespace(project_id=project_id),
        reconciliation=SimpleNamespace(
            new_requirements=(
                SimpleNamespace(
                    name="Live smoke requirement",
                    description="Controlled requirement",
                    expected_date=date(2026, 10, 9),
                ),
            )
        ),
    )
    session = MagicMock()
    follow_ups = MagicMock()
    follow_ups.session = session
    follow_ups.reconcile.return_value = SimpleNamespace(follow_up=SimpleNamespace(id=uuid4()))
    service = RequirementReviewDecisionService(
        session=session,
        review_repository=_Reviews(review),
        lineage_repository=lineage,
        requirement_repository=requirements,
        context_service=context,
        follow_up_lifecycle_service=follow_ups,
    )
    policy_result = SimpleNamespace(
        decision=PolicyDecision.REVIEW_REQUIRED,
        requirement_effects=(),
        evidence_ids=(lineage.list_policy_evidence.return_value[0].id,),
        new_requirement_results=(SimpleNamespace(decision=PolicyDecision.REVIEW_REQUIRED),),
    )
    return service, review, transition, lineage, requirements, follow_ups, session, policy_result


def test_approve_new_requirement_creates_authoritative_requirement_and_correspondence_origin_follow_up(monkeypatch):
    service, review, transition, lineage, requirements, follow_ups, session, policy_result = _service()
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    result = service.approve(review.id, operator_subject="operator")

    assert result.action is RequirementReviewAction.APPROVE
    assert review.status is ReviewStatus.APPROVED
    assert requirements.created[0].expected_date == date(2026, 10, 9)
    assert transition.status is TransitionStatus.PREVIEWED
    lineage.mark_transition_applied.assert_called_once()
    follow_ups.reconcile.assert_called_once_with(
        requirements.created[0].id,
        originating_state_transition_id=transition.id,
        correspondence_event_id=review.correspondence_event_id,
        ai_proposal_id=transition.ai_proposal_id,
        policy_evaluation_id=transition.policy_evaluation_id,
        actor_type="authenticated_operator",
        actor_identifier="operator",
    )
    assert lineage.create_audit_event.call_args.kwargs["event_type"] == REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT
    assert session.commit.call_count == 1


def test_reject_resolves_without_requirement_or_follow_up(monkeypatch):
    service, review, transition, lineage, requirements, follow_ups, session, _ = _service()

    result = service.reject(review.id, operator_subject="operator")

    assert result.action is RequirementReviewAction.REJECT
    assert review.status is ReviewStatus.REJECTED
    assert requirements.created == []
    follow_ups.reconcile.assert_not_called()
    lineage.mark_transition_rejected.assert_called_once_with(transition)
    assert lineage.create_audit_event.call_args.kwargs["event_type"] == REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT
    assert session.commit.call_count == 1


def test_stale_revalidation_blocks_before_authoritative_writes(monkeypatch):
    service, review, transition, lineage, requirements, follow_ups, session, policy_result = _service()
    policy_result.decision = PolicyDecision.REJECT_PROPOSAL
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    with pytest.raises(RequirementReviewDecisionError, match="no longer review-applicable"):
        service.approve(review.id, operator_subject="operator")

    assert requirements.created == []
    follow_ups.reconcile.assert_not_called()
    session.rollback.assert_called_once()


def test_repeated_approval_is_idempotent_without_second_application(monkeypatch):
    service, review, _, _, requirements, follow_ups, _, policy_result = _service()
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    service.approve(review.id, operator_subject="operator")
    repeated = service.approve(review.id, operator_subject="operator")

    assert repeated.idempotent_replay is True
    assert len(requirements.created) == 1
    assert follow_ups.reconcile.call_count == 1
