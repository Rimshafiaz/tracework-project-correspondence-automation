from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.requirement_policy import NewRequirementPolicyResult, RequirementPolicyResult, RequirementPolicyRule, RequirementTransitionEffect
from app.models.enums import PolicyDecision, RequirementState


def _effect() -> RequirementTransitionEffect:
    return RequirementTransitionEffect(
        requirement_id=uuid4(),
        observed_state=RequirementState.OPEN,
        current_state=RequirementState.OPEN,
        proposed_state=RequirementState.PARTIAL,
        proposed_expected_date=None,
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=(RequirementPolicyRule.OPEN_TO_PARTIAL,),
        reasons=("M11 proposed the low-risk transition.",),
        evidence_ids=(uuid4(),),
    )


def test_transition_effect_preserves_strict_requirement_history() -> None:
    effect = _effect()

    assert effect.observed_state is RequirementState.OPEN
    assert effect.current_state is RequirementState.OPEN
    assert effect.proposed_state is RequirementState.PARTIAL
    assert effect.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert effect.evidence_ids


def test_transition_effect_requires_an_actual_change_and_matching_reasons() -> None:
    effect = _effect()
    values = effect.model_dump()
    values["proposed_state"] = RequirementState.OPEN
    with pytest.raises(ValidationError, match="M11-proposed change"):
        RequirementTransitionEffect.model_validate(values)

    values = effect.model_dump()
    values["reasons"] = ("first", "second")
    with pytest.raises(ValidationError, match="each effect rule"):
        RequirementTransitionEffect.model_validate(values)


def test_new_requirement_policy_result_can_only_require_review() -> None:
    values = {
        "proposal_index": 0,
        "decision": PolicyDecision.REVIEW_REQUIRED,
        "triggered_rule_ids": (RequirementPolicyRule.NEW_REQUIREMENT,),
        "reasons": ("Human review is required.",),
        "evidence_ids": (uuid4(),),
    }
    assert NewRequirementPolicyResult(**values).proposal_index == 0

    values["decision"] = PolicyDecision.ALLOW_AUTO_ACTION
    with pytest.raises(ValidationError, match="must require review"):
        NewRequirementPolicyResult(**values)


def test_policy_result_requires_stable_unique_rules_and_reasons() -> None:
    effect = _effect()
    result = RequirementPolicyResult(
        proposal_id=uuid4(),
        policy_version="requirement-policy/1",
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        requirement_effects=(effect,),
        triggered_rule_ids=(
            RequirementPolicyRule.OPEN_TO_PARTIAL,
            RequirementPolicyRule.AUTO_ELIGIBLE,
        ),
        reasons=("Low-risk transition.", "All deterministic checks passed."),
        evidence_ids=effect.evidence_ids,
    )

    assert result.requirement_effects == (effect,)
    values = result.model_dump()
    values["evidence_ids"] = (effect.evidence_ids[0], effect.evidence_ids[0])
    with pytest.raises(ValidationError, match="must be unique"):
        RequirementPolicyResult.model_validate(values)
