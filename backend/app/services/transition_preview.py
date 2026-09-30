from collections.abc import Sequence
from uuid import UUID

from app.contracts.transition_preview import PolicyEvaluationSnapshot, RequirementEffect, StateTransitionPreview, TransitionState
from app.models.enums import PolicyDecision, TransitionDisposition

_DISPOSITIONS = {
    PolicyDecision.ALLOW_AUTO_ACTION: TransitionDisposition.AUTO_APPLY,
    PolicyDecision.REVIEW_REQUIRED: TransitionDisposition.REVIEW,
    PolicyDecision.REJECT_PROPOSAL: TransitionDisposition.BLOCK,
}


def build_state_transition_preview(
    *,
    current_state: TransitionState,
    proposed_state: TransitionState,
    evidence_ids: Sequence[UUID],
    policy: PolicyEvaluationSnapshot,
    requirement_effects: Sequence[RequirementEffect] = (),
) -> StateTransitionPreview:
    if current_state.entity_type != proposed_state.entity_type:
        raise ValueError("current and proposed entity types must match")
    if current_state.entity_id != proposed_state.entity_id:
        raise ValueError("current and proposed entity IDs must match")
    return StateTransitionPreview(
        current_state=current_state,
        proposed_state=proposed_state,
        evidence_ids=tuple(evidence_ids),
        policy=policy,
        requirement_effects=tuple(requirement_effects),
        disposition=_DISPOSITIONS[policy.decision],
    )
