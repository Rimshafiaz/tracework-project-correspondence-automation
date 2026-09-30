from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.evaluation.actions import DangerousFailureType
from app.evaluation.contracts import EvaluatedSystem


class MetricName(StrEnum):
    PROJECT_RESOLUTION_ACCURACY = "PROJECT_RESOLUTION_ACCURACY"
    REQUIREMENT_STATE_ACCURACY = "REQUIREMENT_STATE_ACCURACY"
    NEW_REQUIREMENT_DETECTION = "NEW_REQUIREMENT_DETECTION"
    CONFLICT_DETECTION_RATE = "CONFLICT_DETECTION_RATE"
    FALSE_CLOSURE_RATE = "FALSE_CLOSURE_RATE"
    WRONG_PROJECT_AUTO_ACTION_RATE = "WRONG_PROJECT_AUTO_ACTION_RATE"
    DANGEROUS_ACTION_RATE = "DANGEROUS_ACTION_RATE"
    HUMAN_REVIEW_RATE = "HUMAN_REVIEW_RATE"
    UNNECESSARY_REVIEW_RATE = "UNNECESSARY_REVIEW_RATE"
    AUTOMATION_COVERAGE = "AUTOMATION_COVERAGE"


class EvaluationCaseScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    system: EvaluatedSystem
    project_resolution_correct: bool
    requirement_states_correct: int = Field(ge=0)
    requirement_states_total: int = Field(ge=0)
    new_requirement_detection_correct: bool | None = None
    conflict_detection_correct: bool | None = None
    false_closure_count: int = Field(default=0, ge=0)
    wrong_project_auto_action_count: int = Field(default=0, ge=0)
    dangerous_action_count: int = Field(default=0, ge=0)
    review_expected: bool
    review_observed: bool
    safely_automated: bool
    dangerous_failures: tuple[DangerousFailureType, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> "EvaluationCaseScore":
        if self.requirement_states_correct > self.requirement_states_total:
            raise ValueError("correct requirement states cannot exceed the total")
        if self.dangerous_action_count < len(self.dangerous_failures):
            raise ValueError(
                "dangerous action count cannot be smaller than categorized failures"
            )
        if self.safely_automated and (
            self.review_observed or self.dangerous_action_count
        ):
            raise ValueError(
                "safe automation cannot include review or dangerous actions"
            )
        return self


class MetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: MetricName
    observed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "MetricResult":
        if self.observed_count > self.eligible_count:
            raise ValueError("observed count cannot exceed eligible count")
        return self

    @computed_field
    @property
    def rate(self) -> float | None:
        if self.eligible_count == 0:
            return None
        return self.observed_count / self.eligible_count


class EvaluationRunMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    system: EvaluatedSystem
    case_count: int = Field(ge=0)
    metrics: tuple[MetricResult, ...]
    dangerous_failure_case_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_unique_metrics_and_cases(self) -> "EvaluationRunMetrics":
        metric_names = [result.metric for result in self.metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("each metric may appear only once per run")
        if len(self.dangerous_failure_case_ids) != len(
            set(self.dangerous_failure_case_ids)
        ):
            raise ValueError("dangerous failure case IDs must be unique")
        return self
