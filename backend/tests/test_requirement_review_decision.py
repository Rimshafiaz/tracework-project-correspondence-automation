from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.ai.requirement_schemas import RequirementCorrectionKind, RequirementCorrectionProposal, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.contracts.requirement_review_decision import RequirementReviewAction
from app.models.enums import PolicyDecision, RequirementState, ReviewStatus, ReviewType, TransitionDisposition, TransitionStatus
from app.services.requirement_review_decision import (
    REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT,
    REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT,
    RequirementReviewDecisionError,
    RequirementReviewDecisionCode,
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
            corrections=(),
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


def _correction_service(kind=RequirementCorrectionKind.CORRECTION, *, extra_support=False):
    service, review, transition, lineage, requirements, follow_ups, session, policy_result = _service()
    review.review_type = ReviewType.RETRACTION_CORRECTION
    proposal = lineage.get_proposal_for_update.return_value
    requirement_id = uuid4()
    project_id = UUID(transition.current_state["project_id"])
    prior = SimpleNamespace(id=uuid4(), project_id=project_id, requirement_id=requirement_id)
    source = SimpleNamespace(id=uuid4(), project_id=project_id, requirement_id=requirement_id)
    source_ref = RequirementSourceEvidence(
        correspondence_event_id=proposal.correspondence_event_id,
        source_field=ResolverSourceField.BODY,
        excerpt="The earlier date is corrected.",
    )
    correction = RequirementCorrectionProposal(
        kind=kind,
        requirement_id=requirement_id,
        previous_state=RequirementState.OPEN,
        previous_expected_date=date(2026, 10, 10),
        target_evidence_item_ids=(prior.id,),
        proposed_expected_date=(date(2026, 10, 20) if kind is RequirementCorrectionKind.CORRECTION else None),
        evidence=(source_ref,),
        interpretation="Explicit later correspondence.",
    )
    reconciliation = RequirementReconciliation(corrections=(correction,))
    proposal.structured_output = reconciliation.model_dump(mode="json")
    transition.proposed_state = {"correction_candidates": [correction.model_dump(mode="json")]}
    context = service.context.build.return_value
    context.reconciliation = reconciliation
    context.proposal_evidence = (SimpleNamespace(
        evidence_item_id=source.id,
        correspondence_event_id=proposal.correspondence_event_id,
        attachment_id=None,
        requirement_id=requirement_id,
        source_type="body",
        excerpt=source_ref.excerpt,
    ),)
    requirement = SimpleNamespace(
        id=requirement_id, project_id=project_id,
        state=RequirementState.OPEN, expected_date=date(2026, 10, 10),
    )
    requirements.get_for_update = lambda requested: requirement if requested == requirement_id else None
    def apply(item, *, state, expected_date):
        item.state = state
        item.expected_date = expected_date
        return item
    requirements.apply_authorized_change = MagicMock(side_effect=apply)
    valid = [prior, source]
    if extra_support:
        valid.append(SimpleNamespace(id=uuid4(), project_id=project_id, requirement_id=requirement_id))
    lineage.list_valid_requirement_evidence_for_update.return_value = valid
    lineage.list_policy_evidence.return_value = [prior, source]
    policy_result.requirement_effects = ()
    policy_result.new_requirement_results = ()
    policy_result.evidence_ids = (prior.id, source.id)
    return service, review, transition, lineage, requirements, follow_ups, session, policy_result, requirement, prior, source


def test_approved_date_correction_applies_reviewed_value_once_and_preserves_prior_lineage(monkeypatch):
    service, review, transition, lineage, requirements, follow_ups, session, policy_result, requirement, prior, source = _correction_service()
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    result = service.approve(review.id, operator_subject="operator")
    replay = service.approve(review.id, operator_subject="operator")

    assert result.applied_requirement_ids == (requirement.id,)
    assert replay.idempotent_replay is True
    assert requirement.expected_date == date(2026, 10, 20)
    assert transition.proposed_state["correction_candidates"][0]["previous_expected_date"] == "2026-10-10"
    assert lineage.invalidate_evidence.call_args.args[0] is prior
    assert source not in [call.args[0] for call in lineage.invalidate_evidence.call_args_list]
    assert requirements.apply_authorized_change.call_count == 1
    follow_ups.reconcile.assert_called_once()
    assert session.commit.call_count == 2


def test_retraction_requires_complete_prior_support_and_applies_once(monkeypatch):
    service, review, _, lineage, requirements, follow_ups, _, policy_result, requirement, prior, _ = _correction_service(RequirementCorrectionKind.RETRACTION)
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    result = service.approve(review.id, operator_subject="operator")
    replay = service.approve(review.id, operator_subject="operator")

    assert result.applied_requirement_ids == (requirement.id,)
    assert replay.idempotent_replay is True
    assert requirement.state is RequirementState.RETRACTED
    assert lineage.invalidate_evidence.call_args.args[0] is prior
    assert follow_ups.reconcile.call_count == 1
    assert requirements.apply_authorized_change.call_count == 1


def test_unaccounted_support_blocks_retraction_without_partial_writes(monkeypatch):
    service, review, _, lineage, requirements, follow_ups, session, policy_result, requirement, _, _ = _correction_service(
        RequirementCorrectionKind.RETRACTION, extra_support=True
    )
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    with pytest.raises(RequirementReviewDecisionError) as caught:
        service.approve(review.id, operator_subject="operator")

    assert caught.value.code is RequirementReviewDecisionCode.REMAINING_SUPPORTING_EVIDENCE
    assert requirement.state is RequirementState.OPEN
    lineage.invalidate_evidence.assert_not_called()
    requirements.apply_authorized_change.assert_not_called()
    follow_ups.reconcile.assert_not_called()
    assert review.status is ReviewStatus.PENDING
    session.rollback.assert_called_once_with()


def test_stale_correction_blocks_before_evidence_mutation(monkeypatch):
    service, review, _, lineage, requirements, _, session, policy_result, requirement, _, _ = _correction_service()
    requirement.expected_date = date(2026, 10, 15)
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)

    with pytest.raises(RequirementReviewDecisionError, match="changed after correction review"):
        service.approve(review.id, operator_subject="operator")

    lineage.invalidate_evidence.assert_not_called()
    requirements.apply_authorized_change.assert_not_called()
    session.rollback.assert_called_once_with()


def test_cross_project_or_invalidated_target_blocks_correction(monkeypatch):
    service, review, _, lineage, requirements, _, session, policy_result, requirement, prior, source = _correction_service()
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)
    requirement.project_id = uuid4()
    with pytest.raises(RequirementReviewDecisionError, match="changed after correction review"):
        service.approve(review.id, operator_subject="operator")
    lineage.invalidate_evidence.assert_not_called()

    requirement.project_id = service.context.build.return_value.m11_snapshot.project_id
    lineage.list_valid_requirement_evidence_for_update.return_value = [source]
    with pytest.raises(RequirementReviewDecisionError, match="targeted evidence changed"):
        service.approve(review.id, operator_subject="operator")
    lineage.invalidate_evidence.assert_not_called()
    requirements.apply_authorized_change.assert_not_called()
    assert session.rollback.call_count == 2


def test_follow_up_failure_rolls_back_correction_transaction(monkeypatch):
    service, review, _, lineage, _, follow_ups, session, policy_result, _, _, _ = _correction_service()
    monkeypatch.setattr("app.services.requirement_review_decision.evaluate_requirement_policy", lambda _context: policy_result)
    follow_ups.reconcile.side_effect = RuntimeError("follow-up write failed")

    with pytest.raises(RuntimeError, match="follow-up write failed"):
        service.approve(review.id, operator_subject="operator")

    lineage.invalidate_evidence.assert_called_once()
    assert review.status is ReviewStatus.PENDING
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_wrong_review_type_cannot_use_requirement_application():
    service, review, _, lineage, requirements, follow_ups, session, _ = _service()
    review.review_type = ReviewType.DOCUMENT_REVISION

    with pytest.raises(RequirementReviewDecisionError, match="not a requirement review"):
        service.approve(review.id, operator_subject="operator")

    assert requirements.created == []
    lineage.mark_transition_applied.assert_not_called()
    follow_ups.reconcile.assert_not_called()
    session.rollback.assert_called_once_with()


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
