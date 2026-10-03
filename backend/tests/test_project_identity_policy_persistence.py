from types import SimpleNamespace
from uuid import uuid4

from app.ai.schemas import ResolutionStatus
from app.contracts.project_identity_policy import ProjectIdentityPolicyResult, ProjectIdentityRule
from app.models.enums import PolicyDecision
from app.services.policy import PROJECT_IDENTITY_POLICY_VERSION, persist_project_identity_policy_result


class FakeLineageRepository:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.lookups = []
        self.created = []

    def get_policy_evaluation(self, **values):
        self.lookups.append(values)
        return self.existing

    def create_policy_evaluation(self, **values):
        evaluation = SimpleNamespace(id=uuid4(), **values)
        self.created.append(values)
        return evaluation


def _result() -> ProjectIdentityPolicyResult:
    evidence_id = uuid4()
    return ProjectIdentityPolicyResult(
        proposal_id=uuid4(),
        resolver_status=ResolutionStatus.MATCHED,
        policy_version=PROJECT_IDENTITY_POLICY_VERSION,
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=(
            ProjectIdentityRule.EXACT_PROJECT_CODE,
            ProjectIdentityRule.KNOWN_PROJECT_CONTACT,
            ProjectIdentityRule.AUTO_PROJECT_CODE_AND_CONTACT,
        ),
        reasons=(
            "The correspondence contains an exact project-code match.",
            "The sender is a known contact for the proposed project.",
            "The combined signals permit automatic resolution.",
        ),
        evidence_ids=(evidence_id,),
    )


def test_persist_policy_result_creates_versioned_evaluation_and_evidence_links() -> None:
    result = _result()
    repository = FakeLineageRepository()

    persisted = persist_project_identity_policy_result(result, repository)

    assert persisted.created is True
    assert persisted.evaluation is not None
    assert repository.lookups == [
        {
            "ai_proposal_id": result.proposal_id,
            "policy_version": "project-identity/1",
        }
    ]
    assert repository.created == [
        {
            "ai_proposal_id": result.proposal_id,
            "policy_version": "project-identity/1",
            "decision": PolicyDecision.ALLOW_AUTO_ACTION,
            "triggered_rule_ids": [
                "PID-201-EXACT-PROJECT-CODE",
                "PID-204-KNOWN-PROJECT-CONTACT",
                "PID-401-AUTO-PROJECT-CODE-AND-CONTACT",
            ],
            "reasons": list(result.reasons),
            "evidence_item_ids": result.evidence_ids,
        }
    ]


def test_existing_proposal_version_evaluation_is_returned_without_rewrite() -> None:
    result = _result()
    existing = SimpleNamespace(
        id=uuid4(),
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=["historical-rule"],
    )
    repository = FakeLineageRepository(existing=existing)

    persisted = persist_project_identity_policy_result(result, repository)

    assert persisted.created is False
    assert persisted.evaluation is existing
    assert existing.decision is PolicyDecision.REVIEW_REQUIRED
    assert existing.triggered_rule_ids == ["historical-rule"]
    assert repository.created == []
