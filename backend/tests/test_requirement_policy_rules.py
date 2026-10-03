from app.contracts.requirement_policy import RequirementPolicyRule
from app.services.policy.requirement_rules import REQUIREMENT_POLICY_VERSION, reason_for_requirement_policy_rule


def test_requirement_policy_version_is_readable_and_stable() -> None:
    assert REQUIREMENT_POLICY_VERSION == "requirement-policy/1"


def test_every_requirement_policy_rule_has_a_human_readable_reason() -> None:
    reasons = [reason_for_requirement_policy_rule(rule) for rule in RequirementPolicyRule]

    assert all(reason.strip() for reason in reasons)
    assert len(reasons) == len(RequirementPolicyRule)


def test_auto_eligibility_reason_does_not_claim_semantic_proof() -> None:
    reason = reason_for_requirement_policy_rule(RequirementPolicyRule.AUTO_ELIGIBLE)

    assert "did not independently reinterpret" in reason
