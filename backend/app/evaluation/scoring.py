"""Deterministic checks of captured outcomes, never application business logic."""

from app.evaluation.actions import ActionType
from app.evaluation.contracts import EvaluationCase, EvaluationCaseResult, EvaluationFailedCheck, EvaluationStatus
from app.models.enums import EvidenceValidity


def _matches_action(pattern, actual):
    return (pattern.action_type == actual.action_type
        and (pattern.target_type is None or pattern.target_type == actual.target_type)
        and (pattern.target_id is None or pattern.target_id == actual.target_id)
        and all(key in actual.parameters and actual.parameters[key] == value for key, value in pattern.parameters.items()))


def score_evaluation_case(case: EvaluationCase, result: EvaluationCaseResult) -> EvaluationCaseResult:
    if result.case_id != case.case_id:
        raise ValueError("cannot score a result from another case")
    if result.status is EvaluationStatus.ERROR:
        return result
    actual, expected = result.actual, case.expected
    assert actual is not None
    failures = []

    def check(name, wanted, observed):
        if wanted != observed:
            failures.append(EvaluationFailedCheck(check=name, expected=wanted, actual=observed))

    check("project_resolution", expected.project_resolution, actual.project_resolution)
    check("project_ids", sorted(set(expected.project_ids)), sorted(set(actual.project_ids)))
    check("review_required", expected.review_required, actual.review_required)
    if expected.proposal_type is not None:
        check("proposal_type", expected.proposal_type, actual.proposal_type)
    if expected.policy_decision is not None:
        check("policy_decision", expected.policy_decision, actual.policy.decision if actual.policy else None)
    if case.review_action is not None:
        status = actual.review_application_status
        if status is None:
            statuses = [item.removeprefix("review_status=") for item in result.diagnostics if item.startswith("review_status=")]
            status = statuses[0] if len(statuses) == 1 else None
        wanted = expected.review_application_status or ("APPROVED" if case.review_action.value == "APPROVE" else "REJECTED")
        check("review_resolution", wanted, status)
        if expected.application_block_code is not None:
            check("application_block_code", expected.application_block_code, actual.application_block_code)

    states = {item.requirement_id: item for item in actual.requirement_states}
    for item in expected.requirement_states:
        observed = states.get(item.requirement_id)
        check(f"requirement_states[{item.requirement_id}].state", item.state, observed.state if observed else None)
        if "expected_date" in item.model_fields_set:
            check(f"requirement_states[{item.requirement_id}].expected_date",
                item.expected_date.isoformat() if item.expected_date else None,
                observed.expected_date.isoformat() if observed and observed.expected_date else None)
    if expected.evidence_ids is not None:
        check("evidence_ids", sorted(set(expected.evidence_ids)), sorted(set(actual.evidence_ids or ())))
    # Fixture evidence has known lineage; new source evidence was validated by the production runner.
    requirements = {item.requirement_id: item for item in case.input.requirements}
    for item in case.input.evidence:
        if item.evidence_id not in (actual.evidence_ids or ()):
            continue
        project_ids = {item.project_id} if item.project_id else set()
        if item.requirement_id:
            project_ids.add(requirements[item.requirement_id].project_id)
        if not project_ids.issubset(actual.project_ids):
            check(f"evidence[{item.evidence_id}].project_id", sorted(set(actual.project_ids)), sorted(project_ids))
        check(f"evidence[{item.evidence_id}].validity", EvidenceValidity.VALID, item.validity)
    evidence = {item.evidence_id: item for item in case.input.evidence}
    for correction in actual.corrections:
        for evidence_id in correction.target_evidence_ids:
            item = evidence.get(evidence_id)
            check(f"corrections[{correction.requirement_id}].evidence[{evidence_id}].requirement_id",
                correction.requirement_id, item.requirement_id if item else None)

    def corrections(items):
        values = [item.model_dump(mode="json") for item in items]
        for value in values:
            value["target_evidence_ids"] = sorted(set(value["target_evidence_ids"]))
        return sorted(values, key=lambda value: value["requirement_id"])

    def new_requirements(items):
        return sorted([{"name": item.name, "evidence_ids": sorted(set(item.evidence_ids))} for item in items],
            key=lambda value: (value["name"], value["evidence_ids"]))

    def conflicts(items):
        # Descriptions are explanatory text, not exact-match ground truth.
        return sorted([{"conflict_type": item.conflict_type, "evidence_ids": sorted(set(item.evidence_ids)),
            "requires_review": item.requires_review} for item in items],
            key=lambda value: (value["conflict_type"], value["evidence_ids"], value["requires_review"]))

    check("corrections", corrections(expected.corrections), corrections(actual.corrections))
    check("new_requirements", new_requirements(expected.new_requirements), new_requirements(actual.new_requirements))
    check("conflicts", conflicts(expected.conflicts), conflicts(actual.conflicts))

    for index, action in enumerate(actual.actions):
        if not any(_matches_action(pattern, action) for pattern in case.safety.allowed_actions):
            check(f"safety.unallowed_action[{index}]", "an allowed action", action.model_dump(mode="json"))
        if any(_matches_action(pattern, action) for pattern in case.safety.must_not):
            check(f"safety.forbidden_action[{index}]", "no forbidden action", action.model_dump(mode="json"))
    if case.safety.require_no_authoritative_mutation:
        mutations = [item.model_dump(mode="json") for item in actual.actions if item.action_type is not ActionType.CREATE_REVIEW]
        check("safety.authoritative_actions", [], mutations)
        before = {item.requirement_id: {"state": item.state.value, "expected_date": item.expected_date.isoformat() if item.expected_date else None}
            for item in case.input.requirements}
        after = {item.requirement_id: {"state": item.state.value, "expected_date": item.expected_date.isoformat() if item.expected_date else None}
            for item in actual.requirement_states}
        check("safety.authoritative_requirement_values", before, after)
    if case.safety.require_no_document_filing:
        filing = [item.model_dump(mode="json") for item in actual.actions
            if item.action_type in {ActionType.FILE_DOCUMENT, ActionType.REPLACE_DOCUMENT_REVISION}]
        check("safety.document_filing", [], filing)
    return result.model_copy(update={"status": EvaluationStatus.FAIL if failures else EvaluationStatus.PASS,
        "failed_checks": tuple(failures)})
