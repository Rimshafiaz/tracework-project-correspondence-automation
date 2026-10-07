from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts.requirement_policy import RequirementPolicyResult, RequirementPolicyRule, RequirementTransitionEffect
from app.models.enums import PolicyDecision, RequirementState, TransitionDisposition, TransitionStatus
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationError, RequirementPolicyAuthorizationService
from app.services.follow_up_lifecycle import FollowUpLifecycleService


class FakeLineageRepository:
    def __init__(self, proposal) -> None:
        self.proposal = proposal
        self.evaluation = None
        self.transition = None
        self.policy_evidence_ids = []
        self.audits = []
        self.proposal_lock_count = 0

    def get_proposal_for_update(self, proposal_id):
        self.proposal_lock_count += 1
        return self.proposal if self.proposal.id == proposal_id else None

    def get_policy_evaluation(self, **_values):
        return self.evaluation

    def create_policy_evaluation(self, **values):
        self.policy_evidence_ids = list(values["evidence_item_ids"])
        self.evaluation = SimpleNamespace(id=uuid4(), **values)
        return self.evaluation

    def list_policy_evidence(self, _evaluation_id):
        return [SimpleNamespace(id=item) for item in self.policy_evidence_ids]

    def get_state_transition(self, **_values):
        return self.transition

    def get_state_transition_for_update(self, **_values):
        return self.transition

    def create_transition(self, **values):
        self.transition = SimpleNamespace(
            id=uuid4(),
            status=TransitionStatus.PREVIEWED,
            applied_at=None,
            **values,
        )
        return self.transition

    def mark_transition_applied(self, transition, *, applied_at):
        transition.status = TransitionStatus.APPLIED
        transition.applied_at = applied_at
        return transition

    def mark_transition_rejected(self, transition):
        transition.status = TransitionStatus.REJECTED
        return transition

    def get_audit_event(self, *, event_type, policy_evaluation_id, project_id=None):
        return next(
            (
                audit
                for audit in self.audits
                if audit.event_type == event_type
                and audit.policy_evaluation_id == policy_evaluation_id
                and audit.project_id == project_id
            ),
            None,
        )

    def create_audit_event(self, **values):
        values.setdefault("project_id", None)
        audit = SimpleNamespace(id=uuid4(), **values)
        self.audits.append(audit)
        return audit


class FakeRequirementRepository:
    def __init__(self, requirements, *, fail_on_id=None) -> None:
        self.requirements = {item.id: item for item in requirements}
        self.fail_on_id = fail_on_id
        self.locked_ids = []

    def get_for_update(self, requirement_id):
        self.locked_ids.append(requirement_id)
        return self.requirements.get(requirement_id)

    def apply_authorized_change(self, requirement, *, state, expected_date):
        if requirement.id == self.fail_on_id:
            raise RuntimeError("requirement write failed")
        requirement.state = state
        requirement.expected_date = expected_date
        return requirement


def _fixture(*, decision=PolicyDecision.ALLOW_AUTO_ACTION):
    proposal_id = uuid4()
    event_id = uuid4()
    project_id = uuid4()
    requirement_id = uuid4()
    evidence_id = uuid4()
    proposal = SimpleNamespace(id=proposal_id, correspondence_event_id=event_id)
    context = SimpleNamespace(
        proposal_id=proposal_id,
        m11_snapshot=SimpleNamespace(project_id=project_id),
        reconciliation=SimpleNamespace(new_requirements=()),
    )
    effect_decision = (
        PolicyDecision.ALLOW_AUTO_ACTION
        if decision is PolicyDecision.ALLOW_AUTO_ACTION
        else decision
    )
    rule = (
        RequirementPolicyRule.OPEN_TO_PARTIAL
        if decision is PolicyDecision.ALLOW_AUTO_ACTION
        else RequirementPolicyRule.M11_CONCERN
        if decision is PolicyDecision.REVIEW_REQUIRED
        else RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED
    )
    effect = RequirementTransitionEffect(
        requirement_id=requirement_id,
        observed_state=RequirementState.OPEN,
        current_state=RequirementState.OPEN,
        proposed_state=RequirementState.PARTIAL,
        decision=effect_decision,
        triggered_rule_ids=(rule,),
        reasons=("Deterministic fixture reason.",),
        evidence_ids=(evidence_id,),
    )
    result = RequirementPolicyResult(
        proposal_id=proposal_id,
        policy_version="requirement-policy/1",
        decision=decision,
        requirement_effects=(effect,),
        triggered_rule_ids=(rule,),
        reasons=("Deterministic fixture reason.",),
        evidence_ids=(evidence_id,),
    )
    requirement = SimpleNamespace(
        id=requirement_id,
        project_id=project_id,
        state=RequirementState.OPEN,
        expected_date=None,
    )
    return proposal, context, result, requirement


def _service(proposal, context, requirements, *, fail_on_id=None):
    session = MagicMock(spec=Session)
    lineage = FakeLineageRepository(proposal)
    requirement_repository = FakeRequirementRepository(
        requirements,
        fail_on_id=fail_on_id,
    )
    context_service = MagicMock()
    follow_up_lifecycle = MagicMock(spec=FollowUpLifecycleService)
    follow_up_lifecycle.session = session
    context_service.build.return_value = context
    service = RequirementPolicyAuthorizationService(
        session=session,
        context_service=context_service,
        lineage_repository=lineage,
        requirement_repository=requirement_repository,
        follow_up_lifecycle_service=follow_up_lifecycle,
    )
    return service, session, lineage, requirement_repository, context_service, follow_up_lifecycle


def test_allowed_bundle_is_applied_and_committed_once() -> None:
    proposal, context, result, requirement = _fixture()
    service, session, lineage, requirements, context_service, follow_up_lifecycle = _service(
        proposal, context, (requirement,)
    )

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ):
        authorization = service.authorize(proposal.id)

    assert requirement.state is RequirementState.PARTIAL
    assert authorization.applied_requirement_ids == (requirement.id,)
    assert authorization.transition.status is TransitionStatus.APPLIED
    assert len(lineage.audits) == 2
    assert lineage.proposal_lock_count == 1
    assert requirements.locked_ids == [requirement.id]
    context_service.build.assert_called_once_with(
        proposal,
        lock_current_requirements=True,
    )
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    follow_up_lifecycle.reconcile.assert_called_once_with(
        requirement.id,
        originating_state_transition_id=authorization.transition.id,
        correspondence_event_id=proposal.correspondence_event_id,
        ai_proposal_id=proposal.id,
        policy_evaluation_id=authorization.evaluation.id,
    )


@pytest.mark.parametrize(
    "decision,expected_status",
    [
        (PolicyDecision.REVIEW_REQUIRED, TransitionStatus.PREVIEWED),
        (PolicyDecision.REJECT_PROPOSAL, TransitionStatus.REJECTED),
    ],
)
def test_non_allowed_bundle_never_mutates_requirement(decision, expected_status) -> None:
    proposal, context, result, requirement = _fixture(decision=decision)
    service, session, lineage, requirements, _, follow_up_lifecycle = _service(
        proposal, context, (requirement,)
    )

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ):
        authorization = service.authorize(proposal.id)

    assert requirement.state is RequirementState.OPEN
    assert requirements.locked_ids == []
    assert authorization.applied_requirement_ids == ()
    assert authorization.transition.status is expected_status
    assert len(lineage.audits) == 1
    session.commit.assert_called_once_with()
    follow_up_lifecycle.reconcile.assert_not_called()


def test_retry_reuses_applied_bundle_without_duplicate_mutation_or_audit() -> None:
    proposal, context, result, requirement = _fixture()
    service, session, lineage, requirements, context_service, follow_up_lifecycle = _service(
        proposal, context, (requirement,)
    )

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ):
        first = service.authorize(proposal.id)
        repeated = service.authorize(proposal.id)

    assert first.applied_requirement_ids == (requirement.id,)
    assert repeated.applied_requirement_ids == ()
    assert requirements.locked_ids == [requirement.id]
    assert context_service.build.call_count == 1
    assert len(lineage.audits) == 2
    assert session.commit.call_count == 2
    follow_up_lifecycle.reconcile.assert_called_once()


def test_write_failure_rolls_back_entire_authorization() -> None:
    proposal, context, result, requirement = _fixture()
    service, session, _, _, _, _ = _service(
        proposal,
        context,
        (requirement,),
        fail_on_id=requirement.id,
    )

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ), pytest.raises(RuntimeError, match="requirement write failed"):
        service.authorize(proposal.id)

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_follow_up_failure_rolls_back_authoritative_mutation_transaction() -> None:
    proposal, context, result, requirement = _fixture()
    service, session, _, _, _, lifecycle = _service(
        proposal,
        context,
        (requirement,),
    )
    lifecycle.reconcile.side_effect = RuntimeError("follow-up write failed")

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ), pytest.raises(RuntimeError, match="follow-up write failed"):
        service.authorize(proposal.id)

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_multi_requirement_failure_rolls_back_once_without_commit() -> None:
    proposal, context, result, first = _fixture()
    second = SimpleNamespace(
        id=uuid4(),
        project_id=first.project_id,
        state=RequirementState.OPEN,
        expected_date=None,
    )
    second_effect = result.requirement_effects[0].model_copy(
        update={
            "requirement_id": second.id,
            "evidence_ids": (uuid4(),),
        }
    )
    result = result.model_copy(
        update={
            "requirement_effects": (*result.requirement_effects, second_effect),
            "evidence_ids": (
                *result.evidence_ids,
                *second_effect.evidence_ids,
            ),
        }
    )
    service, session, _, _, _, _ = _service(
        proposal,
        context,
        (first, second),
        fail_on_id=second.id,
    )

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ), pytest.raises(RuntimeError, match="requirement write failed"):
        service.authorize(proposal.id)

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()


def test_changed_requirement_aborts_instead_of_applying_stale_effect() -> None:
    proposal, context, result, requirement = _fixture()
    requirement.state = RequirementState.PARTIAL
    service, session, _, _, _, _ = _service(proposal, context, (requirement,))

    with patch(
        "app.services.policy.requirement_authorization.evaluate_requirement_policy",
        return_value=result,
    ), pytest.raises(
        RequirementPolicyAuthorizationError,
        match="changed after policy evaluation",
    ):
        service.authorize(proposal.id)

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
