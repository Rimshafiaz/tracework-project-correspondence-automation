import asyncio
import json

import pytest
from pydantic import ValidationError

from app.evaluation.batch import run_evaluation_cases
from app.evaluation.contracts import EvaluationBatchResult, EvaluationCaseResult
from test_evaluation_scoring import _case, _result


def test_sequential_batch_counts_pass_fail_error_and_continues(monkeypatch):
    cases = [_case(case_id=f"case-{index}") for index in range(4)]
    calls = []

    async def run(case, **kwargs):
        calls.append(case.case_id)
        if case.case_id == "case-1":
            return _result(case, review_required=True)
        if case.case_id == "case-2":
            return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Controlled model failure")
        return _result(case)

    monkeypatch.setattr("app.evaluation.batch.run_evaluation_case", run)
    summary = asyncio.run(run_evaluation_cases(cases, engine=None, settings=None))
    assert calls == [item.case_id for item in cases]
    assert (summary.total, summary.passed, summary.failed, summary.errors) == (4, 2, 1, 1)
    assert [item.status.value for item in summary.results] == ["PASS", "FAIL", "ERROR", "PASS"]
    assert json.loads(summary.model_dump_json())["total"] == 4
    assert summary.results[2].failed_checks == ()


def test_unexpected_execution_exception_is_error_and_does_not_stop_batch(monkeypatch):
    async def run(case, **kwargs):
        if case.case_id == "broken":
            raise RuntimeError("Private diagnostic data")
        return _result(case)
    monkeypatch.setattr("app.evaluation.batch.run_evaluation_case", run)
    result = asyncio.run(run_evaluation_cases([_case(case_id="broken"), _case(case_id="next")], engine=None, settings=None))
    assert result.errors == 1 and result.passed == 1
    assert result.results[0].error == "batch execution: RuntimeError"
    assert result.results[0].failed_checks == ()


def test_empty_batch_and_unscored_result_guard():
    summary = asyncio.run(run_evaluation_cases([], engine=None, settings=None))
    assert (summary.total, summary.passed, summary.failed, summary.errors) == (0, 0, 0, 0)
    case = _case()
    with pytest.raises(ValidationError, match="must be scored"):
        EvaluationBatchResult(results=(_result(case),))
