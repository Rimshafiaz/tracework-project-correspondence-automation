from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.models.enums import PolicyDecision, RequirementState, TransitionDisposition


class TransitionState(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_type: str
    entity_id: UUID
    values: dict[str, JsonValue]


class RequirementEffect(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: UUID
    current_state: RequirementState
    proposed_state: RequirementState


class PolicyEvaluationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    policy_version: str
    decision: PolicyDecision
    triggered_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]


class StateTransitionPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_state: TransitionState
    proposed_state: TransitionState
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    policy: PolicyEvaluationSnapshot
    requirement_effects: tuple[RequirementEffect, ...] = ()
    document_effects: tuple[()] = ()
    follow_up_effects: tuple[()] = ()
    disposition: TransitionDisposition

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return value
