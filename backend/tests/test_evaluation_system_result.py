import pytest
from pydantic import ValidationError

from app.evaluation.actions import ActionType
from app.evaluation.contracts import ActionExpectation, EvaluatedSystem, EvaluationPolicyResult, EvaluationSystemResult, ExpectedProjectResolution
from app.models.enums import PolicyDecision


def test_one_shot_baseline_uses_common_outcome_and_action_schema() -> None:
    result = EvaluationSystemResult(
        system=EvaluatedSystem.ONE_SHOT_BASELINE,
        project_resolution=ExpectedProjectResolution.MATCHED,
        project_ids=("project-alpha",),
        review_required=False,
        actions=(
            ActionExpectation(
                action_type=ActionType.LINK_CORRESPONDENCE_TO_PROJECT,
                target_type="project",
                target_id="project-alpha",
            ),
        ),
    )

    assert result.project_ids == ("project-alpha",)
    assert result.actions[0].target_id == "project-alpha"
    assert result.policy is None
    assert "state_transition_id" not in EvaluationSystemResult.model_fields


@pytest.mark.parametrize(
    "system",
    [EvaluatedSystem.ONE_SHOT_WITH_POLICY, EvaluatedSystem.TRACEWORK],
)
def test_policy_enabled_systems_report_the_policy_version(
    system: EvaluatedSystem,
) -> None:
    result = EvaluationSystemResult(
        system=system,
        project_resolution=ExpectedProjectResolution.REVIEW_REQUIRED,
        review_required=True,
        policy=EvaluationPolicyResult(
            policy_version="v1",
            decision=PolicyDecision.REVIEW_REQUIRED,
            triggered_rule_ids=("identity-conflict",),
            reasons=("Conflicting identity evidence",),
        ),
    )

    assert result.policy is not None
    assert result.policy.policy_version == "v1"


def test_policy_enabled_result_rejects_missing_policy() -> None:
    with pytest.raises(ValidationError, match="must report their policy result"):
        EvaluationSystemResult(
            system=EvaluatedSystem.TRACEWORK,
            project_resolution=ExpectedProjectResolution.NO_MATCH,
            review_required=False,
        )


def test_plain_baseline_rejects_policy_metadata() -> None:
    with pytest.raises(ValidationError, match="cannot report a policy result"):
        EvaluationSystemResult(
            system=EvaluatedSystem.ONE_SHOT_BASELINE,
            project_resolution=ExpectedProjectResolution.NO_MATCH,
            review_required=False,
            policy=EvaluationPolicyResult(
                policy_version="v1",
                decision=PolicyDecision.REVIEW_REQUIRED,
                triggered_rule_ids=(),
                reasons=(),
            ),
        )
