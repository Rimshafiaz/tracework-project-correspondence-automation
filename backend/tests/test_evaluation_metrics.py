import pytest
from pydantic import ValidationError

from app.evaluation.actions import DangerousFailureType
from app.evaluation.contracts import EvaluatedSystem
from app.evaluation.metrics import EvaluationCaseScore, EvaluationRunMetrics, MetricName, MetricResult


def test_metric_result_preserves_raw_counts_and_calculates_rate() -> None:
    result = MetricResult(
        metric=MetricName.DANGEROUS_ACTION_RATE,
        observed_count=1,
        eligible_count=30,
    )

    assert result.observed_count == 1
    assert result.eligible_count == 30
    assert result.rate == pytest.approx(1 / 30)


def test_metric_rate_is_none_when_no_case_is_eligible() -> None:
    result = MetricResult(
        metric=MetricName.CONFLICT_DETECTION_RATE,
        observed_count=0,
        eligible_count=0,
    )

    assert result.rate is None


def test_case_score_rejects_false_safe_automation() -> None:
    with pytest.raises(ValidationError, match="safe automation"):
        EvaluationCaseScore(
            case_id="case-one",
            system=EvaluatedSystem.TRACEWORK,
            project_resolution_correct=True,
            requirement_states_correct=1,
            requirement_states_total=1,
            dangerous_action_count=1,
            review_expected=False,
            review_observed=False,
            safely_automated=True,
            dangerous_failures=(DangerousFailureType.FALSE_REQUIREMENT_CLOSURE,),
        )


def test_case_score_rejects_impossible_requirement_count() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        EvaluationCaseScore(
            case_id="case-one",
            system=EvaluatedSystem.ONE_SHOT_BASELINE,
            project_resolution_correct=True,
            requirement_states_correct=2,
            requirement_states_total=1,
            review_expected=False,
            review_observed=False,
            safely_automated=False,
        )


def test_run_metrics_reject_duplicate_metric_names() -> None:
    metric = MetricResult(
        metric=MetricName.PROJECT_RESOLUTION_ACCURACY,
        observed_count=1,
        eligible_count=1,
    )

    with pytest.raises(ValidationError, match="only once"):
        EvaluationRunMetrics(
            run_id="run-one",
            system=EvaluatedSystem.TRACEWORK,
            case_count=1,
            metrics=(metric, metric),
        )
