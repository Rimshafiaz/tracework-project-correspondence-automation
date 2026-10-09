import asyncio
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text

from app.ai.requirement_schemas import ExistingRequirementImpact, NewRequirementProposal, RequirementCorrectionProposal, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import CandidateSignalReference, ProjectResolution, ProjectResolverInput, ResolutionEvidence
from app.contracts.requirement_reconciliation import RequirementReconcilerInput
from app.core.config import Settings
from app.evaluation import DatasetSplit, EvaluationCase, EvaluationStatus, load_dataset
from app.evaluation.actions import ActionType
from app.evaluation.project_resolver import _fixture_uuid
from app.evaluation.runner import run_evaluation_case
from app.evaluation.scoring import score_evaluation_case


class ProjectAgent:
    def __init__(self, review=False):
        self.review = review

    async def run(self, prompt):
        context = ProjectResolverInput.model_validate_json(prompt)
        candidate = context.candidates.candidates[0]
        signal = candidate.signals[0]
        reference = CandidateSignalReference(project_id=candidate.project_id,
            **{key: getattr(signal, key) for key in CandidateSignalReference.model_fields if key != "project_id"})
        return SimpleNamespace(output=ProjectResolution(status="REVIEW_REQUIRED" if self.review else "MATCHED",
            concerns=("AMBIGUOUS_CANDIDATES",) if self.review else (), project_ids=(candidate.project_id,),
            evidence=(ResolutionEvidence(project_id=candidate.project_id, signal_references=(reference,), interpretation="Controlled model output"),)))


class RequirementAgent:
    def __init__(self, state="PARTIAL", fail=False):
        self.state, self.fail = state, fail

    async def run(self, prompt):
        if self.fail:
            raise RuntimeError("Sensitive provider details must not leak")
        context = RequirementReconcilerInput.model_validate_json(prompt)
        evidence = RequirementSourceEvidence(correspondence_event_id=context.correspondence.correspondence_event_id,
            source_field="BODY", excerpt=context.correspondence.body)
        if self.state == "NEW":
            return SimpleNamespace(output=RequirementReconciliation(new_requirements=(NewRequirementProposal(
                name="New reviewed obligation", expected_date="2026-10-20", evidence=(evidence,), interpretation="Controlled model output"),)))
        if self.state in {"CORRECTION", "RETRACTION", "PARTIAL_RETRACTION"}:
            requirement = context.requirements[0]
            return SimpleNamespace(output=RequirementReconciliation(corrections=(RequirementCorrectionProposal(
                kind="RETRACTION" if self.state == "PARTIAL_RETRACTION" else self.state,
                requirement_id=requirement.requirement_id, previous_state=requirement.current_state,
                previous_expected_date=requirement.expected_date,
                target_evidence_item_ids=tuple(item.evidence_item_id for item in context.existing_valid_evidence
                    if item.requirement_id == requirement.requirement_id and (self.state != "PARTIAL_RETRACTION"
                        or item.evidence_item_id == _fixture_uuid("evidence", "clear-evidence"))),
                proposed_expected_date="2026-10-20" if self.state == "CORRECTION" else None,
                evidence=(evidence,), interpretation="Controlled model output"),)))
        return SimpleNamespace(output=RequirementReconciliation(existing_impacts=(ExistingRequirementImpact(
            requirement_id=context.requirements[0].requirement_id, disposition="UPDATE_PROPOSED",
            proposed_state=self.state, evidence=(evidence,), interpretation="Controlled model output"),)))


def _case(**changes):
    payload = load_dataset(DatasetSplit.DEVELOPMENT)[0].model_dump(mode="json")
    payload.update(changes)
    return EvaluationCase.model_validate(payload)


@pytest.fixture
def engine(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for rollback-only PostgreSQL integration")
    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation must never send Gmail")
    monkeypatch.setattr("app.adapters.gmail.reply_client.send_gmail_reply", forbidden)
    database = create_engine(url, connect_args={"connect_timeout": 5})
    yield database
    database.dispose()


def _run(engine, case, agent=None, project_agent=None):
    settings = Settings(_env_file=None, app_env="test", database_url=str(engine.url),
        gmail_enabled=False, drive_enabled=False)
    return asyncio.run(run_evaluation_case(case, engine=engine, settings=settings,
        project_agent=project_agent or ProjectAgent(), requirement_agent=agent or RequirementAgent()))


def _assert_clean(engine, case):
    schema = f"tracework_eval_{_fixture_uuid('case', case.case_id).hex}"
    with engine.connect() as connection:
        assert not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :name)"), {"name": schema})


def test_real_pipeline_is_ordered_unscored_and_repeatably_isolated(engine):
    case = _case()
    result = _run(engine, case)
    assert result.status is EvaluationStatus.UNSCORED, result.error
    assert result.diagnostics == ("PROJECT_RESOLUTION", "POLICY:PROJECT", "REQUIREMENT_RECONCILIATION", "POLICY:REQUIREMENT")
    assert result.actual.requirement_states[0].state.value == "PARTIAL"  # Expected SATISFIED is deliberately not scored.
    assert any(action.action_type is ActionType.CHANGE_REQUIREMENT_STATE for action in result.actual.actions)
    assert len(result.models) == 2
    assert not result.failed_checks and result.error is None
    _assert_clean(engine, case)
    assert _run(engine, case).actual == result.actual
    _assert_clean(engine, case)


def test_project_only_stage_does_not_authorize_or_mutate(engine):
    case = _case(stages=["PROJECT_RESOLUTION"])
    result = _run(engine, case)
    assert result.status is EvaluationStatus.UNSCORED, result.error
    assert result.actual.policy is None
    assert not result.actual.actions
    assert result.actual.requirement_states[0].state.value == "OPEN"
    _assert_clean(engine, case)


def test_real_runner_result_is_scored_without_reexecuting_case(engine):
    payload = _case().model_dump(mode="json")
    payload["expected"]["requirement_states"][0]["state"] = "PARTIAL"
    payload["safety"]["allowed_actions"] = [
        {"action_type": "LINK_CORRESPONDENCE_TO_PROJECT", "target_id": "project-alpha"},
        {"action_type": "CHANGE_REQUIREMENT_STATE", "target_id": "approval", "parameters": {"state": "PARTIAL"}},
    ]
    case = EvaluationCase.model_validate(payload)
    unscored = _run(engine, case)
    assert unscored.status is EvaluationStatus.UNSCORED, unscored.error
    assert score_evaluation_case(case, unscored).status is EvaluationStatus.PASS
    payload["expected"]["requirement_states"][0]["state"] = "SATISFIED"
    assert score_evaluation_case(EvaluationCase.model_validate(payload), unscored).status is EvaluationStatus.FAIL
    _assert_clean(engine, case)


def test_case_writes_never_target_public_tables(engine):
    case = _case()
    schema = f"tracework_eval_{_fixture_uuid('case', case.case_id).hex}"
    writes = []
    def inspect_write(connection, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip()
        for prefix in ("INSERT INTO ", "UPDATE ", "DELETE FROM "):
            if sql.startswith(prefix):
                assert sql.startswith((f'{prefix}{schema}.', f'{prefix}"{schema}".'))
                writes.append(prefix)
    event.listen(engine, "before_cursor_execute", inspect_write)
    try:
        result = _run(engine, case)
        assert result.status is EvaluationStatus.UNSCORED, result.error
        assert writes
    finally:
        event.remove(engine, "before_cursor_execute", inspect_write)
    _assert_clean(engine, case)


@pytest.mark.parametrize("action,state", [(None, "OPEN"), ("APPROVE", "SATISFIED"), ("REJECT", "OPEN")])
def test_review_application_requires_explicit_action(engine, action, state):
    stages = ["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY"]
    if action:
        stages.append("REVIEW_APPLICATION")
    case = _case(stages=stages, review_action=action)
    result = _run(engine, case, RequirementAgent("SATISFIED"))
    assert result.status is EvaluationStatus.UNSCORED, result.error
    assert result.actual.requirement_states[0].state.value == state
    assert ("REVIEW_APPLICATION" in result.diagnostics) == bool(action)
    _assert_clean(engine, case)


@pytest.mark.parametrize("action", ["APPROVE", "REJECT"])
def test_explicit_project_review_uses_existing_decision_service(engine, action):
    case = _case(stages=["PROJECT_RESOLUTION", "POLICY", "REVIEW_APPLICATION"], review_action=action)
    result = _run(engine, case, project_agent=ProjectAgent(review=True))
    assert result.status is EvaluationStatus.UNSCORED, result.error
    linked = any(item.action_type is ActionType.LINK_CORRESPONDENCE_TO_PROJECT for item in result.actual.actions)
    assert linked == (action == "APPROVE")
    assert "REVIEW_APPLICATION" in result.diagnostics
    _assert_clean(engine, case)


def test_execution_failure_is_error_and_cleans_case_state(engine):
    case = _case()
    result = _run(engine, case, RequirementAgent(fail=True))
    assert result.status is EvaluationStatus.ERROR
    assert result.error == "REQUIREMENT_RECONCILIATION: RuntimeError"
    assert not result.failed_checks and result.actual is None
    _assert_clean(engine, case)


@pytest.mark.parametrize("effect", ["NEW", "CORRECTION", "RETRACTION"])
def test_reviewed_effects_use_production_application_and_are_captured(engine, effect):
    case = _case(stages=["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"],
        review_action="APPROVE")
    result = _run(engine, case, RequirementAgent(effect))
    assert result.status is EvaluationStatus.UNSCORED, result.error
    if effect == "NEW":
        assert result.actual.new_requirements[0].evidence_ids
        assert len(result.actual.requirement_states) == 2
        assert any(item.action_type is ActionType.CREATE_FOLLOW_UP for item in result.actual.actions)
    else:
        assert result.actual.corrections[0].kind.value == effect
        assert result.actual.corrections[0].target_evidence_ids == ("clear-evidence",)
        requirement = result.actual.requirement_states[0]
        if effect == "CORRECTION":
            assert requirement.expected_date.isoformat() == "2026-10-20"
        else:
            assert requirement.state.value == "RETRACTED"
            assert any(item.action_type is ActionType.INVALIDATE_EVIDENCE for item in result.actual.actions)
    _assert_clean(engine, case)


def test_real_remaining_support_block_is_an_outcome_that_can_pass(engine):
    payload = _case().model_dump(mode="json")
    payload["input"]["evidence"].append(dict(payload["input"]["evidence"][0], evidence_id="remaining-support"))
    payload.update(stages=["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"], review_action="APPROVE")
    payload["expected"].update(review_required=True, policy_decision="REVIEW_REQUIRED",
        review_application_status="BLOCKED", application_block_code="REMAINING_SUPPORTING_EVIDENCE",
        requirement_states=[{"requirement_id": "approval", "state": "OPEN"}],
        corrections=[{"kind": "RETRACTION", "requirement_id": "approval", "target_evidence_ids": ["clear-evidence"]}])
    payload["safety"] = {"allowed_actions": [
        {"action_type": "LINK_CORRESPONDENCE_TO_PROJECT", "target_id": "project-alpha"},
        {"action_type": "CREATE_REVIEW"}], "must_not": [
        {"action_type": "CHANGE_REQUIREMENT_STATE"}, {"action_type": "INVALIDATE_EVIDENCE"},
        {"action_type": "CREATE_FOLLOW_UP"}]}
    case = EvaluationCase.model_validate(payload)
    result = _run(engine, case, RequirementAgent("PARTIAL_RETRACTION"))
    assert result.status is EvaluationStatus.UNSCORED, result.error
    assert result.actual.application_block_code == "REMAINING_SUPPORTING_EVIDENCE"
    assert "review_status=PENDING" in result.diagnostics
    scored = score_evaluation_case(case, result)
    assert scored.status is EvaluationStatus.PASS, scored.failed_checks
    payload["expected"]["application_block_code"] = "different-domain-code"
    assert score_evaluation_case(EvaluationCase.model_validate(payload), result).status is EvaluationStatus.FAIL
    _assert_clean(engine, case)


@pytest.mark.parametrize("domain_block", [True, False])
def test_known_stale_domain_block_is_not_an_unexpected_execution_error(engine, monkeypatch, domain_block):
    from app.services.requirement_review_decision import RequirementReviewDecisionError
    def reject_apply(*args, **kwargs):
        if domain_block:
            raise RequirementReviewDecisionError("requirement proposal is stale")
        raise RuntimeError("Unexpected private execution failure")
    monkeypatch.setattr("app.evaluation.runner.RequirementReviewDecisionService.approve", reject_apply)
    case = _case(stages=["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION", "POLICY", "REVIEW_APPLICATION"], review_action="APPROVE")
    result = _run(engine, case, RequirementAgent("SATISFIED"))
    if domain_block:
        assert result.status is EvaluationStatus.UNSCORED, result.error
        assert result.actual.review_application_status == "BLOCKED"
        assert result.actual.application_block_code is None
        assert result.actual.requirement_states[0].state.value == "OPEN"
        assert score_evaluation_case(case, result).status is EvaluationStatus.FAIL
    else:
        assert result.status is EvaluationStatus.ERROR
        assert result.error == "REVIEW_APPLICATION: RuntimeError"
    _assert_clean(engine, case)


@pytest.mark.parametrize("stages", [
    ["POLICY", "PROJECT_RESOLUTION"],
    ["PROJECT_RESOLUTION", "REQUIREMENT_RECONCILIATION"],
])
def test_invalid_stage_dependencies_fail_before_database_or_model_work(stages):
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    result = asyncio.run(run_evaluation_case(_case(stages=stages), engine=engine,
        settings=Settings(_env_file=None, app_env="test", gmail_enabled=False, drive_enabled=False)))
    assert result.status is EvaluationStatus.ERROR
    assert result.diagnostics == ()
