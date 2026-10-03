import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.requirement_schemas import ExistingRequirementImpact, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.contracts.requirement_policy import AuthoritativeProjectLinkRecord, RequirementCurrentRecord, RequirementPolicyContext, RequirementPolicyResult, RequirementPolicyRule, RequirementTransitionEffect
from app.contracts.requirement_reconciliation import RequirementContextSnapshot, RequirementSnapshot
from app.models.enums import PolicyDecision, ProposalType, RequirementState, TransitionDisposition
from app.services.policy.requirement_persistence import REQUIREMENT_RECONCILIATION_ENTITY_TYPE, RequirementPolicyPersistenceError, persist_requirement_policy_result, persist_requirement_transition_preview


class FakeLineageRepository:
    def __init__(self, *, evaluation=None, transition=None) -> None:
        self.evaluation = evaluation
        self.transition = transition
        self.created_evaluations = []
        self.created_transitions = []
        self.policy_evidence_ids = []

    def get_policy_evaluation(self, **_values):
        return self.evaluation

    def create_policy_evaluation(self, **values):
        self.policy_evidence_ids = list(values["evidence_item_ids"])
        self.evaluation = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=values["ai_proposal_id"],
            policy_version=values["policy_version"],
            decision=values["decision"],
            triggered_rule_ids=values["triggered_rule_ids"],
            reasons=values["reasons"],
        )
        self.created_evaluations.append(values)
        return self.evaluation

    def list_policy_evidence(self, _evaluation_id):
        return [SimpleNamespace(id=item) for item in self.policy_evidence_ids]

    def get_state_transition(self, **_values):
        return self.transition

    def create_transition(self, **values):
        self.transition = SimpleNamespace(id=uuid4(), **values)
        self.created_transitions.append(values)
        return self.transition


def _context_and_result():
    proposal_id = uuid4()
    project_id = uuid4()
    event_id = uuid4()
    link_id = uuid4()
    requirement_id = uuid4()
    evidence_id = uuid4()
    body = "Neutral evidence records progress."
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    reference = RequirementSourceEvidence(
        correspondence_event_id=event_id,
        source_field=ResolverSourceField.BODY,
        excerpt="records progress",
    )
    reconciliation = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.PARTIAL,
                evidence=(reference,),
                interpretation="Neutral fixture interpretation.",
            ),
        )
    )
    context = RequirementPolicyContext(
        proposal_id=proposal_id,
        proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        correspondence_event_id=event_id,
        reconciliation=reconciliation,
        m11_snapshot=RequirementContextSnapshot(
            project_id=project_id,
            authoritative_project_link_id=link_id,
            correspondence_event_id=event_id,
            body_sha256=body_hash,
            requirements=(
                RequirementSnapshot(
                    requirement_id=requirement_id,
                    name="Neutral requirement",
                    current_state=RequirementState.OPEN,
                ),
            ),
        ),
        authoritative_project_link=AuthoritativeProjectLinkRecord(
            link_id=link_id,
            correspondence_event_id=event_id,
            project_id=project_id,
        ),
        current_requirements=(
            RequirementCurrentRecord(
                requirement_id=requirement_id,
                project_id=project_id,
                name="Neutral requirement",
                state=RequirementState.OPEN,
            ),
        ),
        current_body_sha256=body_hash,
    )
    effect = RequirementTransitionEffect(
        requirement_id=requirement_id,
        observed_state=RequirementState.OPEN,
        current_state=RequirementState.OPEN,
        proposed_state=RequirementState.PARTIAL,
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=(
            RequirementPolicyRule.OPEN_TO_PARTIAL,
            RequirementPolicyRule.AUTO_ELIGIBLE,
        ),
        reasons=(
            "M11 proposed the low-risk transition.",
            "All deterministic checks passed.",
        ),
        evidence_ids=(evidence_id,),
    )
    result = RequirementPolicyResult(
        proposal_id=proposal_id,
        policy_version="requirement-policy/1",
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        requirement_effects=(effect,),
        triggered_rule_ids=effect.triggered_rule_ids,
        reasons=effect.reasons,
        evidence_ids=(evidence_id,),
    )
    return context, result


def test_persists_versioned_policy_and_strict_bundle_preview() -> None:
    context, result = _context_and_result()
    repository = FakeLineageRepository()

    persisted = persist_requirement_policy_result(result, repository)
    transition = persist_requirement_transition_preview(
        context=context,
        result=result,
        evaluation=persisted.evaluation,
        repository=repository,
    )

    assert persisted.created is True
    assert repository.created_evaluations[0]["policy_version"] == "requirement-policy/1"
    assert transition.created is True
    assert transition.preview.disposition is TransitionDisposition.AUTO_APPLY
    assert transition.preview.requirement_effects[0] == result.requirement_effects[0]
    stored = repository.created_transitions[0]
    assert stored["affected_entity_type"] == REQUIREMENT_RECONCILIATION_ENTITY_TYPE
    assert stored["affected_entity_id"] == context.proposal_id
    assert stored["requirement_effects"] == [
        result.requirement_effects[0].model_dump(mode="json")
    ]
    assert stored["proposed_state"]["requirements"][0]["proposed_state"] == "PARTIAL"


def test_persistence_reuses_historical_evaluation_and_transition() -> None:
    context, result = _context_and_result()
    repository = FakeLineageRepository()
    evaluation = persist_requirement_policy_result(result, repository).evaluation
    first = persist_requirement_transition_preview(
        context=context,
        result=result,
        evaluation=evaluation,
        repository=repository,
    )

    persisted_again = persist_requirement_policy_result(result, repository)
    second = persist_requirement_transition_preview(
        context=context,
        result=result,
        evaluation=evaluation,
        repository=repository,
    )

    assert persisted_again.created is False
    assert second.created is False
    assert second.transition is first.transition
    assert len(repository.created_evaluations) == 1
    assert len(repository.created_transitions) == 1


def test_no_change_policy_creates_no_transition() -> None:
    context, result = _context_and_result()
    result = RequirementPolicyResult(
        proposal_id=result.proposal_id,
        policy_version=result.policy_version,
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=(RequirementPolicyRule.NO_CHANGE,),
        reasons=("M11 proposed no authoritative requirement change.",),
    )
    repository = FakeLineageRepository()
    evaluation = persist_requirement_policy_result(result, repository).evaluation

    persisted = persist_requirement_transition_preview(
        context=context,
        result=result,
        evaluation=evaluation,
        repository=repository,
    )

    assert persisted.preview is None
    assert persisted.transition is None
    assert repository.created_transitions == []


def test_historical_evaluation_mismatch_is_not_silently_rewritten() -> None:
    context, result = _context_and_result()
    repository = FakeLineageRepository()
    evaluation = persist_requirement_policy_result(result, repository).evaluation
    evaluation.decision = PolicyDecision.REVIEW_REQUIRED

    with pytest.raises(RequirementPolicyPersistenceError, match="does not match"):
        persist_requirement_transition_preview(
            context=context,
            result=result,
            evaluation=evaluation,
            repository=repository,
        )
