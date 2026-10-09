import json
from uuid import UUID

import pytest

from app.evaluation import DatasetSplit, EvaluationCase, EvaluationCaseResult, EvaluationSystemResult, load_dataset, score_evaluation_case
from app.evaluation.project_resolver import _fixture_uuid


def _case(**changes):
    payload = load_dataset(DatasetSplit.DEVELOPMENT)[0].model_dump(mode="json")
    payload.update(changes)
    return EvaluationCase.model_validate(payload)


def _result(case, **changes):
    values = case.expected.model_dump(exclude={"policy_decision"})
    values.update(system="TRACEWORK", policy={"policy_version": "test-policy", "decision": "ALLOW_AUTO_ACTION",
        "triggered_rule_ids": (), "reasons": ()})
    values.update(changes)
    return EvaluationCaseResult(case_id=case.case_id, status="UNSCORED", actual=EvaluationSystemResult(**values))


def test_exact_match_passes_and_one_mismatch_fails():
    case = _case()
    assert score_evaluation_case(case, _result(case)).status.value == "PASS"
    result = score_evaluation_case(case, _result(case, review_required=True))
    assert result.status.value == "FAIL"
    assert [(item.check, item.expected, item.actual) for item in result.failed_checks] == [("review_required", False, True)]
    assert json.loads(result.model_dump_json())["failed_checks"][0]["actual"] is True


def test_all_mismatches_are_reported_and_execution_error_is_not_scored():
    case = _case()
    result = score_evaluation_case(case, _result(case, project_resolution="NO_MATCH", project_ids=(), review_required=True,
        requirement_states=()))
    assert {item.check for item in result.failed_checks} >= {"project_resolution", "project_ids", "review_required", "requirement_states[approval].state"}
    error = EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Model unavailable")
    assert score_evaluation_case(case, error) is error
    with pytest.raises(ValueError, match="another case"):
        score_evaluation_case(case, error.model_copy(update={"case_id": "other"}))


def test_project_and_evidence_order_do_not_affect_scoring_but_wrong_ids_do():
    payload = _case().model_dump(mode="json")
    project = dict(payload["input"]["candidate_projects"][0], project_id="project-beta", project_code="BETA")
    payload["input"]["candidate_projects"].append(project)
    evidence = dict(payload["input"]["evidence"][0], evidence_id="other-evidence")
    payload["input"]["evidence"].append(evidence)
    payload["expected"].update(project_resolution="MULTI_PROJECT", project_ids=["project-alpha", "project-beta"],
        evidence_ids=["clear-evidence", "other-evidence"])
    case = EvaluationCase.model_validate(payload)
    assert score_evaluation_case(case, _result(case, project_ids=("project-beta", "project-alpha"),
        evidence_ids=("other-evidence", "clear-evidence"))).status.value == "PASS"
    wrong = score_evaluation_case(case, _result(case, evidence_ids=("clear-evidence", "fabricated")))
    assert "evidence_ids" in {item.check for item in wrong.failed_checks}


def test_selected_fixture_evidence_from_wrong_project_fails_even_when_ids_match():
    payload = _case().model_dump(mode="json")
    payload["input"]["candidate_projects"].append(dict(payload["input"]["candidate_projects"][0], project_id="other", project_code="OTHER"))
    payload["input"]["evidence"][0]["project_id"] = "other"
    payload["expected"]["evidence_ids"] = ["clear-evidence"]
    case = EvaluationCase.model_validate(payload)
    result = score_evaluation_case(case, _result(case))
    assert "evidence[clear-evidence].project_id" in {item.check for item in result.failed_checks}


def test_invalidated_selected_evidence_fails_even_when_ids_match():
    payload = _case().model_dump(mode="json")
    payload["input"]["evidence"][0]["validity"] = "INVALIDATED"
    payload["expected"]["evidence_ids"] = ["clear-evidence"]
    case = EvaluationCase.model_validate(payload)
    result = score_evaluation_case(case, _result(case))
    assert "evidence[clear-evidence].validity" in {item.check for item in result.failed_checks}


def test_safety_catches_mutation_even_if_action_capture_is_missing():
    case = _case(safety={"require_no_authoritative_mutation": True})
    result = score_evaluation_case(case, _result(case))  # Input OPEN, actual SATISFIED.
    assert result.status.value == "FAIL"
    assert "safety.authoritative_requirement_values" in {item.check for item in result.failed_checks}


def test_action_patterns_are_whitelists_and_forbidden_parameters_take_precedence():
    case = _case(safety={"allowed_actions": [{"action_type": "CHANGE_REQUIREMENT_STATE", "target_id": "approval"}],
        "must_not": [{"action_type": "CHANGE_REQUIREMENT_STATE", "parameters": {"state": "SATISFIED"}}],
        "require_no_document_filing": True})
    result = score_evaluation_case(case, _result(case, actions=(
        {"action_type": "CHANGE_REQUIREMENT_STATE", "target_id": "approval", "parameters": {"state": "SATISFIED"}},
        {"action_type": "FILE_DOCUMENT", "target_id": "document"},
    )))
    assert {item.check for item in result.failed_checks} >= {"safety.forbidden_action[0]", "safety.unallowed_action[1]", "safety.document_filing"}
    assert score_evaluation_case(case, _result(case, actions=())).status.value == "PASS"  # Allowed is not required.


@pytest.mark.parametrize("kind,state,date", [("CORRECTION", "OPEN", "2026-10-20"), ("RETRACTION", "RETRACTED", None)])
def test_correction_and_retraction_intent_targets_and_authoritative_values(kind, state, date):
    payload = _case().model_dump(mode="json")
    payload["expected"].update(review_required=True, proposal_type="REQUIREMENT_RECONCILIATION", policy_decision="REVIEW_REQUIRED",
        requirement_states=[{"requirement_id": "approval", "state": state, "expected_date": date}],
        corrections=[{"kind": kind, "requirement_id": "approval", "target_evidence_ids": ["clear-evidence"], "proposed_expected_date": date}])
    payload.update(stages=["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"], review_action="APPROVE")
    case = EvaluationCase.model_validate(payload)
    result = _result(case, policy={"policy_version": "test", "decision": "REVIEW_REQUIRED", "triggered_rule_ids": (), "reasons": ()})
    result = result.model_copy(update={"diagnostics": ("review_status=APPROVED",)})
    assert score_evaluation_case(case, result).status.value == "PASS"
    wrong = result.actual.model_dump()
    wrong["requirement_states"][0]["state"] = "PARTIAL"
    wrong["corrections"][0]["target_evidence_ids"] = ("wrong-evidence",)
    failure = score_evaluation_case(case, result.model_copy(update={"actual": EvaluationSystemResult(**wrong)}))
    assert {item.check for item in failure.failed_checks} >= {"corrections", "requirement_states[approval].state"}


def test_policy_proposal_date_and_explicit_reject_outcomes_are_checked():
    payload = _case().model_dump(mode="json")
    payload["expected"].update(policy_decision="REVIEW_REQUIRED", proposal_type="REQUIREMENT_RECONCILIATION", review_required=True)
    payload["expected"]["requirement_states"][0]["expected_date"] = "2026-10-20"
    payload.update(stages=["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"], review_action="REJECT")
    case = EvaluationCase.model_validate(payload)
    result = _result(case, proposal_type="PROJECT_RESOLUTION", requirement_states=({"requirement_id": "approval", "state": "SATISFIED"},))
    result = result.model_copy(update={"diagnostics": ("review_status=APPROVED",)})
    failure = score_evaluation_case(case, result)
    assert {item.check for item in failure.failed_checks} >= {"policy_decision", "proposal_type", "review_resolution", "requirement_states[approval].expected_date"}


def test_conflict_and_new_requirement_checks_ignore_description_and_evidence_order():
    payload = _case().model_dump(mode="json")
    payload["input"]["evidence"].append(dict(payload["input"]["evidence"][0], evidence_id="second"))
    payload["expected"].update(review_required=True, conflicts=[{"conflict_type": "requirement_evidence",
        "evidence_ids": ["clear-evidence", "second"], "description": "Fixture wording"}],
        new_requirements=[{"name": "New obligation", "evidence_ids": ["clear-evidence", "second"]}])
    case = EvaluationCase.model_validate(payload)
    result = _result(case, conflicts=({"conflict_type": "requirement_evidence", "evidence_ids": ("second", "clear-evidence"), "description": "Different explanation"},),
        new_requirements=({"name": "New obligation", "evidence_ids": ("second", "clear-evidence")},))
    assert score_evaluation_case(case, result).status.value == "PASS"
    assert {item.check for item in score_evaluation_case(case, _result(case, conflicts=(), new_requirements=())).failed_checks} == {"conflicts", "new_requirements"}


def _source_grounded_result(case, **changes):
    proposal_id = UUID("c4547c8a-5bbb-4712-a7d5-1e43c27fdf22")
    values = dict(proposal_id=proposal_id, evidence_ids=("runtime-evidence-1",),
        policy={"policy_version": "test", "decision": "REVIEW_REQUIRED", "triggered_rule_ids": (), "reasons": ()},
        new_requirements=({"name": "Visitor access register", "evidence_ids": ("runtime-evidence-1",)},),
        source_evidence=({"evidence_id": "runtime-evidence-1",
            "correspondence_event_id": _fixture_uuid("correspondence", case.input.correspondence.external_event_id),
            "project_id": "larkhaven-pier", "proposal_id": proposal_id, "validity": "VALID"},))
    values.update(changes)
    return _result(case, **values)


def test_runtime_source_grounding_passes_without_predeclared_evidence_id():
    case = load_dataset(DatasetSplit.HELD_OUT)[6]
    assert case.input.evidence == ()
    assert score_evaluation_case(case, _source_grounded_result(case)).status.value == "PASS"


@pytest.mark.parametrize("field,value", [
    ("correspondence_event_id", UUID("8bab6349-fbd2-47b4-96ee-4f1f8e5e33c2")),
    ("project_id", "another-project"),
    ("proposal_id", UUID("fbef550c-47a8-4203-b155-b6aac6eedbc0")),
    ("validity", "INVALIDATED"),
])
def test_runtime_source_grounding_rejects_wrong_or_invalid_lineage(field, value):
    case = load_dataset(DatasetSplit.HELD_OUT)[6]
    result = _source_grounded_result(case)
    evidence = result.actual.source_evidence[0].model_copy(update={field: value})
    result = result.model_copy(update={"actual": result.actual.model_copy(update={"source_evidence": (evidence,)})})
    assert score_evaluation_case(case, result).status.value == "FAIL"


def test_runtime_source_grounding_requires_captured_and_selected_evidence():
    case = load_dataset(DatasetSplit.HELD_OUT)[6]
    for changes in ({"source_evidence": ()}, {"evidence_ids": ()}):
        assert score_evaluation_case(case, _source_grounded_result(case, **changes)).status.value == "FAIL"


def test_source_grounding_does_not_relax_exact_new_requirement_evidence():
    payload = _case().model_dump(mode="json")
    payload["expected"]["new_requirements"] = [{"name": "Named obligation", "evidence_ids": ["clear-evidence"]}]
    case = EvaluationCase.model_validate(payload)
    assert score_evaluation_case(case, _result(case)).status.value == "PASS"
    result = _result(case, new_requirements=({"name": "Named obligation", "evidence_ids": ("runtime-evidence-1",)},))
    assert {item.check for item in score_evaluation_case(case, result).failed_checks} == {"new_requirements"}


def test_source_grounding_cannot_claim_preexisting_fixture_evidence_is_new():
    payload = load_dataset(DatasetSplit.HELD_OUT)[6].model_dump(mode="json")
    payload["input"]["evidence"] = [{"evidence_id": "runtime-evidence-1", "source_type": "body",
        "project_id": "larkhaven-pier", "excerpt": payload["input"]["correspondence"]["body"]}]
    case = EvaluationCase.model_validate(payload)
    assert score_evaluation_case(case, _source_grounded_result(case)).status.value == "FAIL"


def test_required_actions_reuse_matching_and_all_must_occur():
    required = [{"action_type": "INVALIDATE_EVIDENCE", "target_type": "evidence", "target_id": item}
        for item in ("first", "second")]
    case = _case(safety={"allowed_actions": [{"action_type": "INVALIDATE_EVIDENCE"}], "required_actions": required})
    assert score_evaluation_case(case, _result(case, actions=required)).status.value == "PASS"
    result = score_evaluation_case(case, _result(case, actions=required[:1]))
    assert result.status.value == "FAIL"
    assert len(result.failed_checks) == 1
    assert result.failed_checks[0].check == "safety.required_action[1]"
    assert result.failed_checks[0].expected["target_id"] == "second"
    assert result.failed_checks[0].actual[0]["target_id"] == "first"
    assert len(score_evaluation_case(case, _result(case, actions=())).failed_checks) == 2
    extra = required + [{"action_type": "CREATE_REQUIREMENT"}]
    assert "safety.unallowed_action[2]" in {item.check for item in score_evaluation_case(case, _result(case, actions=extra)).failed_checks}


def test_allowed_actions_alone_still_do_not_require_occurrence():
    case = _case(safety={"allowed_actions": [{"action_type": "INVALIDATE_EVIDENCE"}]})
    assert case.safety.required_actions == ()
    assert score_evaluation_case(case, _result(case, actions=())).status.value == "PASS"
