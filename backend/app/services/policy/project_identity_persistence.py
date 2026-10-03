from dataclasses import dataclass

from app.contracts.project_identity_policy import ProjectIdentityPolicyResult
from app.models.policy_evaluation import PolicyEvaluation
from app.repositories.lineage import LineageRepository


@dataclass(frozen=True)
class PersistedProjectIdentityPolicy:
    evaluation: PolicyEvaluation
    created: bool


def persist_project_identity_policy_result(
    result: ProjectIdentityPolicyResult,
    repository: LineageRepository,
) -> PersistedProjectIdentityPolicy:
    existing = repository.get_policy_evaluation(
        ai_proposal_id=result.proposal_id,
        policy_version=result.policy_version,
    )
    if existing is not None:
        return PersistedProjectIdentityPolicy(
            evaluation=existing,
            created=False,
        )

    evaluation = repository.create_policy_evaluation(
        ai_proposal_id=result.proposal_id,
        policy_version=result.policy_version,
        decision=result.decision,
        triggered_rule_ids=[rule.value for rule in result.triggered_rule_ids],
        reasons=list(result.reasons),
        evidence_item_ids=result.evidence_ids,
    )
    return PersistedProjectIdentityPolicy(
        evaluation=evaluation,
        created=True,
    )
