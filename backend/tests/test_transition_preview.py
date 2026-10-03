from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.transition_preview import PolicyEvaluationSnapshot, RequirementEffect, StateTransitionPreview, TransitionState
from app.models.enums import PolicyDecision, RequirementState, TransitionDisposition
from app.services.transition_preview import build_state_transition_preview


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (PolicyDecision.ALLOW_AUTO_ACTION, TransitionDisposition.AUTO_APPLY),
        (PolicyDecision.REVIEW_REQUIRED, TransitionDisposition.REVIEW),
        (PolicyDecision.REJECT_PROPOSAL, TransitionDisposition.BLOCK),
    ],
)
def test_policy_decision_deterministically_selects_disposition(
    decision: PolicyDecision,
    expected: TransitionDisposition,
) -> None:
    requirement_id = uuid4()
    evidence_id = uuid4()
    current = TransitionState(
        entity_type="requirement",
        entity_id=requirement_id,
        values={"state": "OPEN"},
    )
    proposed = TransitionState(
        entity_type="requirement",
        entity_id=requirement_id,
        values={"state": "PARTIAL"},
    )
    policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="v1",
        decision=decision,
        triggered_rule_ids=("rule-1",),
        reasons=("Deterministic policy result",),
    )
    effect = RequirementEffect(
        requirement_id=requirement_id,
        current_state=RequirementState.OPEN,
        proposed_state=RequirementState.PARTIAL,
    )

    preview = build_state_transition_preview(
        current_state=current,
        proposed_state=proposed,
        evidence_ids=[evidence_id],
        policy=policy,
        requirement_effects=[effect],
    )

    assert preview.disposition is expected
    assert preview.evidence_ids == (evidence_id,)
    assert preview.policy.triggered_rule_ids == ("rule-1",)
    assert preview.document_effects == ()
    assert preview.follow_up_effects == ()


def test_builder_is_deterministic_for_identical_inputs() -> None:
    entity_id = uuid4()
    state = TransitionState(
        entity_type="requirement",
        entity_id=entity_id,
        values={"state": "OPEN"},
    )
    policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="v1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=(),
        reasons=("Review required",),
    )
    evidence_ids = [uuid4()]

    first = build_state_transition_preview(
        current_state=state,
        proposed_state=state,
        evidence_ids=evidence_ids,
        policy=policy,
    )
    second = build_state_transition_preview(
        current_state=state,
        proposed_state=state,
        evidence_ids=evidence_ids,
        policy=policy,
    )

    assert first == second


def test_preview_requires_unique_evidence() -> None:
    entity_id = uuid4()
    evidence_id = uuid4()
    state = TransitionState(
        entity_type="requirement",
        entity_id=entity_id,
        values={"state": "OPEN"},
    )
    policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="v1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=(),
        reasons=("Review required",),
    )

    with pytest.raises(ValidationError, match="evidence IDs must be unique"):
        build_state_transition_preview(
            current_state=state,
            proposed_state=state,
            evidence_ids=[evidence_id, evidence_id],
            policy=policy,
        )


def test_review_preview_may_have_no_evidence_but_automatic_effect_may_not() -> None:
    entity_id = uuid4()
    state = TransitionState(
        entity_type="requirement_reconciliation",
        entity_id=entity_id,
        values={"requirements": []},
    )
    review_policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="requirement-policy/1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=("RID-404-M11-CONCERN",),
        reasons=("M11 reported an unresolved concern.",),
    )

    preview = build_state_transition_preview(
        current_state=state,
        proposed_state=state,
        evidence_ids=(),
        policy=review_policy,
    )

    assert preview.evidence_ids == ()

    automatic_policy = review_policy.model_copy(
        update={"decision": PolicyDecision.ALLOW_AUTO_ACTION}
    )
    with pytest.raises(ValidationError, match="automatic requirement effects"):
        build_state_transition_preview(
            current_state=state,
            proposed_state=state,
            evidence_ids=(),
            policy=automatic_policy,
            requirement_effects=[
                RequirementEffect(
                    requirement_id=uuid4(),
                    current_state=RequirementState.OPEN,
                    proposed_state=RequirementState.PARTIAL,
                )
            ],
        )


def test_preview_rejects_mismatched_entities() -> None:
    policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="v1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=(),
        reasons=("Review required",),
    )

    with pytest.raises(ValueError, match="entity IDs must match"):
        build_state_transition_preview(
            current_state=TransitionState(
                entity_type="requirement",
                entity_id=uuid4(),
                values={"state": "OPEN"},
            ),
            proposed_state=TransitionState(
                entity_type="requirement",
                entity_id=uuid4(),
                values={"state": "PARTIAL"},
            ),
            evidence_ids=[uuid4()],
            policy=policy,
        )
