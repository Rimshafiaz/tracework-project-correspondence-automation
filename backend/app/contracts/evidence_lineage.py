from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from app.contracts.requirement_policy import RequirementTransitionEffect
from app.models.enums import (
    EvidenceValidity,
    PolicyDecision,
    ProposalType,
    RequirementState,
    ReviewStatus,
    ReviewType,
    TransitionDisposition,
    TransitionStatus,
)


class LineageCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    LEGACY_PARTIAL = "LEGACY_PARTIAL"


class LineageAttribution(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    HUMAN = "HUMAN"
    NONE = "NONE"


class LineageCorrespondence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    source: str
    sender_identifier: str
    subject: str | None
    body: str
    received_at: datetime


class LineageAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    filename: str
    mime_type: str
    content_hash: str | None


class LineageEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    correspondence_event_id: UUID
    attachment_id: UUID | None
    project_id: UUID | None
    requirement_id: UUID | None
    source_type: str
    excerpt: str
    start_offset: int | None
    end_offset: int | None
    page_number: int | None
    section: str | None
    validity_at_proposal: EvidenceValidity
    validity_at_policy: EvidenceValidity
    validity_at_outcome: EvidenceValidity | None
    current_validity: EvidenceValidity
    invalidated_at: datetime | None
    invalidation_reason: str | None
    linked_to_proposal: bool
    linked_to_policy: bool
    linked_to_transition: bool


class LineageProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    proposal_type: ProposalType
    model_identifier: str
    prompt_version: str
    input_hash: str
    structured_output: dict[str, JsonValue]
    created_at: datetime


class LineagePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    policy_version: str
    decision: PolicyDecision
    triggered_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    evaluated_at: datetime


class LineageTransition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    affected_entity_type: str
    affected_entity_id: UUID
    historical_current_state: dict[str, JsonValue]
    historical_proposed_state: dict[str, JsonValue]
    requirement_effects: tuple[RequirementTransitionEffect, ...]
    disposition: TransitionDisposition
    status: TransitionStatus
    created_at: datetime
    applied_at: datetime | None


class LineageReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    review_type: ReviewType
    status: ReviewStatus
    review_reason: str
    correction_payload: dict[str, JsonValue] | None
    created_at: datetime
    resolved_at: datetime | None


class LineageAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    event_type: str
    actor_type: str
    authenticated_operator_subject: str | None
    operator_supplied_actor_label: str | None
    details: dict[str, JsonValue]
    occurred_at: datetime


class CurrentRequirementState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: UUID
    exists: bool
    project_id: UUID | None
    state: RequirementState | None
    expected_date: date | None


class LineageCurrentState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    linked_project_ids: tuple[UUID, ...]
    requirements: tuple[CurrentRequirementState, ...]


class LineageOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attribution: LineageAttribution
    occurred_at: datetime | None
    authenticated_operator_subject: str | None
    operator_supplied_actor_label: str | None


class EvidenceLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    completeness: LineageCompleteness
    completeness_notes: tuple[str, ...]
    correspondence: LineageCorrespondence
    attachments: tuple[LineageAttachment, ...]
    evidence: tuple[LineageEvidence, ...]
    proposal: LineageProposal
    policy: LineagePolicy
    transition: LineageTransition
    review: LineageReview | None
    audit_events: tuple[LineageAuditEvent, ...]
    historical_outcome: LineageOutcome
    current_state: LineageCurrentState
