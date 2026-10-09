import json

import pytest
from pydantic import ValidationError

from app.evaluation import (
    DatasetSplit, EvaluatedSystem, EvaluationCase, EvaluationCaseResult,
    EvaluationCorrection, EvaluationFailedCheck, EvaluationModelMetadata,
    EvaluationStage, EvaluationStatus, EvaluationSystemResult, load_dataset,
)
from app.models.enums import PolicyDecision, ProposalType


def _case(**changes):
    payload = load_dataset(DatasetSplit.DEVELOPMENT)[2].model_dump(mode="json")
    payload.update(changes)
    return EvaluationCase.model_validate(payload)


def _actual():
    return EvaluationSystemResult(
        system=EvaluatedSystem.TRACEWORK,
        project_resolution="MATCHED", project_ids=("project-alpha",), review_required=True,
        policy={"policy_version": "requirement-policy/1", "decision": "REVIEW_REQUIRED",
                "triggered_rule_ids": (), "reasons": ()},
    )


def test_existing_cases_load_without_conversion_and_select_stages():
    assert len(load_dataset(DatasetSplit.DEVELOPMENT)) == 3
    case = _case(stages=["PROJECT_RESOLUTION"])
    assert case.stages == (EvaluationStage.PROJECT_RESOLUTION,)
    assert case.safety == load_dataset(DatasetSplit.DEVELOPMENT)[2].safety


def test_case_labels_capture_policy_grounding_and_reviewed_retraction():
    case = _case()
    requirement = case.input.requirements[0]
    evidence = case.input.evidence[0]
    expected = case.expected.model_dump(mode="json")
    expected.update(policy_decision="REVIEW_REQUIRED", proposal_type="REQUIREMENT_RECONCILIATION",
                    evidence_ids=[evidence.evidence_id], corrections=[{
                        "requirement_id": requirement.requirement_id, "kind": "RETRACTION",
                        "target_evidence_ids": [evidence.evidence_id],
                    }])
    reviewed = _case(expected=expected, stages=["REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"], review_action="APPROVE")
    assert reviewed.expected.policy_decision is PolicyDecision.REVIEW_REQUIRED
    assert reviewed.expected.proposal_type is ProposalType.REQUIREMENT_RECONCILIATION
    assert reviewed.expected.corrections[0].kind.value == "RETRACTION"
    assert reviewed.review_action.value == "APPROVE"


@pytest.mark.parametrize("changes", [
    {"case_id": " "}, {"stages": []}, {"stages": ["POLICY", "POLICY"]},
    {"stages": ["UNKNOWN"]}, {"stages": ["REVIEW_APPLICATION"]},
    {"review_action": "APPROVE"}, {"send_gmail": True},
])
def test_cases_reject_invalid_or_implicit_execution(changes):
    with pytest.raises(ValidationError):
        _case(**changes)


def test_labels_reject_unseen_evidence_and_wrong_requirement_targets():
    case = _case()
    payload = case.model_dump(mode="json")
    payload["expected"]["evidence_ids"] = ["missing-evidence"]
    with pytest.raises(ValidationError, match="expected evidence must exist"):
        EvaluationCase.model_validate(payload)
    payload["expected"]["evidence_ids"] = []
    payload["expected"]["corrections"] = [{"kind": "RETRACTION", "requirement_id": "missing-requirement",
                                          "target_evidence_ids": [case.input.evidence[0].evidence_id]}]
    with pytest.raises(ValidationError, match="correction requirements must exist"):
        EvaluationCase.model_validate(payload)


def test_correction_can_label_a_replacement_date_without_mutating_fixture():
    correction = EvaluationCorrection(requirement_id="requirement-one", kind="CORRECTION",
        target_evidence_ids=("evidence-one",), proposed_expected_date="2026-10-20")
    assert correction.model_dump(mode="json")["proposed_expected_date"] == "2026-10-20"
    with pytest.raises(ValidationError, match="must be unique"):
        EvaluationCorrection(requirement_id="requirement-one", kind="RETRACTION", target_evidence_ids=("same", "same"))


def test_pass_fail_and_execution_error_are_distinct_json_safe_results():
    actual = _actual()
    metadata = EvaluationModelMetadata(stage="REQUIREMENT_RECONCILIATION", provider="gemini",
                                       model="configured-test-model", prompt_version="requirement-reconciler-v2")
    passed = EvaluationCaseResult(case_id="case-one", status="PASS", actual=actual, models=(metadata,))
    check = EvaluationFailedCheck(check="review_required", expected=False, actual=True)
    failed = EvaluationCaseResult(case_id="case-one", status="FAIL", actual=actual, failed_checks=(check,))
    error = EvaluationCaseResult(case_id="case-one", status="ERROR", error="Model unavailable")
    assert json.loads(passed.model_dump_json())["schema_version"] == 1
    assert EvaluationCaseResult.model_validate_json(failed.model_dump_json()) == failed
    assert error.actual is None
    assert error.status is EvaluationStatus.ERROR


def test_unscored_means_execution_succeeded_without_expectation_checks():
    result = EvaluationCaseResult(case_id="case-one", status="UNSCORED", actual=_actual())
    assert result.status is EvaluationStatus.UNSCORED
    assert not result.failed_checks and result.error is None
    assert EvaluationCaseResult.model_validate_json(result.model_dump_json()) == result


def test_project_only_result_does_not_claim_policy_was_executed():
    result = EvaluationSystemResult(system="TRACEWORK", stages=("PROJECT_RESOLUTION",),
        project_resolution="NO_MATCH", review_required=False)
    assert result.policy is None


def test_expected_application_block_requires_a_review_action_and_blocked_status():
    case = _case()
    payload = case.model_dump(mode="json")
    payload["expected"]["application_block_code"] = "REMAINING_SUPPORTING_EVIDENCE"
    with pytest.raises(ValidationError, match="requires BLOCKED"):
        EvaluationCase.model_validate(payload)
    payload["expected"]["review_application_status"] = "BLOCKED"
    with pytest.raises(ValidationError, match="requires an explicit action"):
        EvaluationCase.model_validate(payload)
    payload.update(stages=["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"], review_action="APPROVE")
    assert EvaluationCase.model_validate(payload).expected.application_block_code == "REMAINING_SUPPORTING_EVIDENCE"


@pytest.mark.parametrize("status,actual,checks,error", [
    ("PASS", None, (), None), ("FAIL", None, (), None),
    ("FAIL", _actual(), (), None),
    ("PASS", _actual(), (EvaluationFailedCheck(check="review", expected=False, actual=True),), None),
    ("ERROR", None, (), None), ("PASS", _actual(), (), "Provider failed"),
    ("UNSCORED", None, (), None), ("UNSCORED", _actual(), (), "Provider failed"),
    ("UNSCORED", _actual(), (EvaluationFailedCheck(check="review", expected=False, actual=True),), None),
])
def test_result_cannot_claim_success_or_mismatch_without_support(status, actual, checks, error):
    with pytest.raises(ValidationError):
        EvaluationCaseResult(case_id="case-one", status=status, actual=actual, failed_checks=checks, error=error)
