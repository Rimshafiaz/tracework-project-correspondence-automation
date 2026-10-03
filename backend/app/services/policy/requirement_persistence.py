from dataclasses import dataclass

from app.contracts.requirement_policy import RequirementPolicyContext, RequirementPolicyResult, RequirementPolicyTransitionPreview
from app.contracts.transition_preview import PolicyEvaluationSnapshot, TransitionState
from app.models.enums import PolicyDecision, TransitionDisposition
from app.models.policy_evaluation import PolicyEvaluation
from app.models.state_transition import StateTransition
from app.repositories.lineage import LineageRepository

REQUIREMENT_RECONCILIATION_ENTITY_TYPE = "requirement_reconciliation"


class RequirementPolicyPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PersistedRequirementPolicy:
    evaluation: PolicyEvaluation
    created: bool


@dataclass(frozen=True)
class PersistedRequirementTransitionPreview:
    preview: RequirementPolicyTransitionPreview | None
    transition: StateTransition | None
    created: bool


def persist_requirement_policy_result(
    result: RequirementPolicyResult,
    repository: LineageRepository,
) -> PersistedRequirementPolicy:
    existing = repository.get_policy_evaluation(
        ai_proposal_id=result.proposal_id,
        policy_version=result.policy_version,
    )
    if existing is not None:
        _require_matching_evaluation(result, existing, repository)
        return PersistedRequirementPolicy(evaluation=existing, created=False)
    evaluation = repository.create_policy_evaluation(
        ai_proposal_id=result.proposal_id,
        policy_version=result.policy_version,
        decision=result.decision,
        triggered_rule_ids=[rule.value for rule in result.triggered_rule_ids],
        reasons=list(result.reasons),
        evidence_item_ids=result.evidence_ids,
    )
    return PersistedRequirementPolicy(evaluation=evaluation, created=True)


def persist_requirement_transition_preview(
    *,
    context: RequirementPolicyContext,
    result: RequirementPolicyResult,
    evaluation: PolicyEvaluation,
    repository: LineageRepository,
) -> PersistedRequirementTransitionPreview:
    if context.proposal_id != result.proposal_id:
        raise RequirementPolicyPersistenceError(
            "policy result does not belong to the supplied M11 proposal"
        )
    _require_matching_evaluation(result, evaluation, repository)
    preview = build_requirement_policy_preview(
        context=context,
        result=result,
        evaluation=evaluation,
    )
    if preview is None:
        return PersistedRequirementTransitionPreview(
            preview=None,
            transition=None,
            created=False,
        )
    existing = repository.get_state_transition(
        policy_evaluation_id=evaluation.id,
        affected_entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
        affected_entity_id=context.proposal_id,
    )
    if existing is not None:
        return PersistedRequirementTransitionPreview(
            preview=preview,
            transition=existing,
            created=False,
        )
    transition = repository.create_transition(
        ai_proposal_id=context.proposal_id,
        policy_evaluation_id=evaluation.id,
        affected_entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
        affected_entity_id=context.proposal_id,
        current_state=preview.current_state.values,
        proposed_state=preview.proposed_state.values,
        requirement_effects=[
            effect.model_dump(mode="json")
            for effect in result.requirement_effects
        ],
        document_effects=[],
        follow_up_effects=[],
        disposition=preview.disposition,
        evidence_item_ids=preview.evidence_ids,
    )
    return PersistedRequirementTransitionPreview(
        preview=preview,
        transition=transition,
        created=True,
    )


def build_requirement_policy_preview(
    *,
    context: RequirementPolicyContext,
    result: RequirementPolicyResult,
    evaluation: PolicyEvaluation,
) -> RequirementPolicyTransitionPreview | None:
    if (
        not result.requirement_effects
        and not result.new_requirement_results
        and result.decision is PolicyDecision.ALLOW_AUTO_ACTION
    ):
        return None
    current_requirements = [
        {
            "requirement_id": str(effect.requirement_id),
            "observed_state": effect.observed_state.value,
            "observed_expected_date": (
                effect.observed_expected_date.isoformat()
                if effect.observed_expected_date is not None
                else None
            ),
            "current_state": effect.current_state.value,
            "current_expected_date": (
                effect.current_expected_date.isoformat()
                if effect.current_expected_date is not None
                else None
            ),
        }
        for effect in result.requirement_effects
    ]
    proposed_requirements = [
        {
            "requirement_id": str(effect.requirement_id),
            "proposed_state": effect.proposed_state.value,
            "proposed_expected_date": (
                effect.proposed_expected_date.isoformat()
                if effect.proposed_expected_date is not None
                else None
            ),
            "decision": effect.decision.value,
        }
        for effect in result.requirement_effects
    ]
    new_requirements = [
        {
            "proposal_index": item.proposal_index,
            **context.reconciliation.new_requirements[
                item.proposal_index
            ].model_dump(mode="json"),
        }
        for item in result.new_requirement_results
    ]
    return RequirementPolicyTransitionPreview(
        current_state=TransitionState(
            entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
            entity_id=context.proposal_id,
            values={
                "project_id": str(context.m11_snapshot.project_id),
                "requirements": current_requirements,
            },
        ),
        proposed_state=TransitionState(
            entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
            entity_id=context.proposal_id,
            values={
                "project_id": str(context.m11_snapshot.project_id),
                "requirements": proposed_requirements,
                "new_requirement_candidates": new_requirements,
            },
        ),
        evidence_ids=result.evidence_ids,
        policy=PolicyEvaluationSnapshot(
            id=evaluation.id,
            policy_version=evaluation.policy_version,
            decision=evaluation.decision,
            triggered_rule_ids=tuple(evaluation.triggered_rule_ids),
            reasons=tuple(evaluation.reasons),
        ),
        requirement_effects=result.requirement_effects,
        disposition={
            PolicyDecision.ALLOW_AUTO_ACTION: TransitionDisposition.AUTO_APPLY,
            PolicyDecision.REVIEW_REQUIRED: TransitionDisposition.REVIEW,
            PolicyDecision.REJECT_PROPOSAL: TransitionDisposition.BLOCK,
        }[result.decision],
    )


def _require_matching_evaluation(
    result: RequirementPolicyResult,
    evaluation: PolicyEvaluation,
    repository: LineageRepository,
) -> None:
    evidence_ids = tuple(
        item.id for item in repository.list_policy_evidence(evaluation.id)
    )
    if (
        evaluation.ai_proposal_id != result.proposal_id
        or evaluation.policy_version != result.policy_version
        or evaluation.decision is not result.decision
        or tuple(evaluation.triggered_rule_ids)
        != tuple(rule.value for rule in result.triggered_rule_ids)
        or tuple(evaluation.reasons) != result.reasons
        or set(evidence_ids) != set(result.evidence_ids)
    ):
        raise RequirementPolicyPersistenceError(
            "persisted policy evaluation does not match the requirement policy result"
        )
