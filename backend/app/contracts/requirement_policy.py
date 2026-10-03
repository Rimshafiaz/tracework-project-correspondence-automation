from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.requirement_schemas import RequirementReconciliation
from app.contracts.requirement_reconciliation import RequirementAttachmentSnapshot, RequirementContextSnapshot
from app.contracts.transition_preview import PolicyEvaluationSnapshot, TransitionState
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType, RequirementState, TransitionDisposition


class RequirementPolicyRule(StrEnum):
    PROPOSAL_TYPE_INVALID = "RID-001-PROPOSAL-TYPE-INVALID"
    CONTEXT_SNAPSHOT_MISSING = "RID-002-CONTEXT-SNAPSHOT-MISSING"
    PROPOSAL_INTEGRITY_FAILED = "RID-003-PROPOSAL-INTEGRITY-FAILED"
    PROJECT_LINK_INVALID = "RID-004-PROJECT-LINK-INVALID"
    REQUIREMENT_NOT_CURRENT = "RID-005-REQUIREMENT-NOT-CURRENT"
    EVIDENCE_MISSING_OR_UNLINKED = "RID-006-EVIDENCE-MISSING-OR-UNLINKED"
    EVIDENCE_INVALIDATED = "RID-007-EVIDENCE-INVALIDATED"
    EVIDENCE_SCOPE_MISMATCH = "RID-008-EVIDENCE-SCOPE-MISMATCH"
    PROVENANCE_INTEGRITY_FAILED = "RID-009-PROVENANCE-INTEGRITY-FAILED"

    REQUIREMENT_STATE_STALE = "RID-100-REQUIREMENT-STATE-STALE"
    EXPECTED_DATE_STALE = "RID-101-EXPECTED-DATE-STALE"
    REQUIREMENT_DEFINITION_STALE = "RID-102-REQUIREMENT-DEFINITION-STALE"
    REQUIREMENT_SET_STALE = "RID-103-REQUIREMENT-SET-STALE"
    SOURCE_CONTEXT_STALE = "RID-104-SOURCE-CONTEXT-STALE"

    NO_CHANGE = "RID-200-NO-CHANGE"

    OPEN_TO_PARTIAL = "RID-300-OPEN-TO-PARTIAL"
    AUTO_ELIGIBLE = "RID-301-AUTO-ELIGIBLE"

    SATISFIED_REQUIRES_REVIEW = "RID-400-SATISFIED-REQUIRES-REVIEW"
    BACKWARD_TRANSITION = "RID-401-BACKWARD-TRANSITION"
    REVIEW_STATE_TRANSITION = "RID-402-REVIEW-STATE-TRANSITION"
    EXPECTED_DATE_REQUIRES_REVIEW = "RID-403-EXPECTED-DATE-REQUIRES-REVIEW"
    M11_CONCERN = "RID-404-M11-CONCERN"
    M11_CONFLICT = "RID-405-M11-CONFLICT"
    NEW_REQUIREMENT = "RID-406-NEW-REQUIREMENT"
    POSSIBLE_DUPLICATE = "RID-407-POSSIBLE-DUPLICATE"
    INSUFFICIENT_SCOPED_EVIDENCE = "RID-408-INSUFFICIENT-SCOPED-EVIDENCE"
    MULTI_IMPACT_ATOMIC_REVIEW = "RID-409-MULTI-IMPACT-ATOMIC-REVIEW"


class RequirementCurrentRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    state: RequirementState
    expected_date: date | None = None

    @field_validator("name")
    @classmethod
    def reject_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("requirement name must not be blank")
        return value


class AuthoritativeProjectLinkRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: UUID
    correspondence_event_id: UUID
    project_id: UUID


class RequirementPolicyEvidenceFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    correspondence_event_id: UUID
    attachment_id: UUID | None = None
    project_id: UUID | None = None
    requirement_id: UUID | None = None
    source_type: str
    excerpt: str
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None
    provenance_metadata: dict[str, object] | None = None
    validity: EvidenceValidity

    @field_validator("source_type", "excerpt")
    @classmethod
    def reject_blank_evidence_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence text fields must not be blank")
        return value


class RequirementCurrentEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    project_id: UUID | None = None
    requirement_id: UUID | None = None
    validity: EvidenceValidity
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequirementPolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    proposal_type: ProposalType
    correspondence_event_id: UUID
    reconciliation: RequirementReconciliation
    m11_snapshot: RequirementContextSnapshot
    authoritative_project_link: AuthoritativeProjectLinkRecord | None
    current_requirements: tuple[RequirementCurrentRecord, ...]
    current_subject_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_attachments: tuple[RequirementAttachmentSnapshot, ...] = ()
    current_snapshot_evidence: tuple[RequirementCurrentEvidenceSnapshot, ...] = ()
    proposal_evidence: tuple[RequirementPolicyEvidenceFact, ...] = ()

    @model_validator(mode="after")
    def require_unique_records(self) -> "RequirementPolicyContext":
        collections = (
            [item.requirement_id for item in self.current_requirements],
            [item.attachment_id for item in self.current_attachments],
            [item.evidence_item_id for item in self.current_snapshot_evidence],
            [item.evidence_item_id for item in self.proposal_evidence],
        )
        if any(len(items) != len(set(items)) for items in collections):
            raise ValueError("requirement policy context records must be unique")
        return self


class RequirementTransitionEffect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: UUID
    observed_state: RequirementState
    observed_expected_date: date | None = None
    current_state: RequirementState
    current_expected_date: date | None = None
    proposed_state: RequirementState
    proposed_expected_date: date | None = None
    decision: PolicyDecision
    triggered_rule_ids: tuple[RequirementPolicyRule, ...] = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("reasons")
    @classmethod
    def reject_blank_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not reason.strip() for reason in value):
            raise ValueError("policy reasons must not be blank")
        return value

    @field_validator("triggered_rule_ids", "evidence_ids")
    @classmethod
    def require_unique_items(cls, value: tuple) -> tuple:
        if len(value) != len(set(value)):
            raise ValueError("transition effect items must be unique")
        return value

    @model_validator(mode="after")
    def validate_effect(self) -> "RequirementTransitionEffect":
        if len(self.triggered_rule_ids) != len(self.reasons):
            raise ValueError("each effect rule requires one human-readable reason")
        if (
            self.proposed_state is self.observed_state
            and self.proposed_expected_date == self.observed_expected_date
        ):
            raise ValueError("a transition effect must contain an M11-proposed change")
        return self


class RequirementPolicyTransitionPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_state: TransitionState
    proposed_state: TransitionState
    evidence_ids: tuple[UUID, ...] = ()
    policy: PolicyEvaluationSnapshot
    requirement_effects: tuple[RequirementTransitionEffect, ...] = ()
    document_effects: tuple[()] = ()
    follow_up_effects: tuple[()] = ()
    disposition: TransitionDisposition

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def validate_preview(self) -> "RequirementPolicyTransitionPreview":
        if (
            self.current_state.entity_type != self.proposed_state.entity_type
            or self.current_state.entity_id != self.proposed_state.entity_id
        ):
            raise ValueError("preview current and proposed entities must match")
        if (
            self.disposition is TransitionDisposition.AUTO_APPLY
            and self.requirement_effects
            and not self.evidence_ids
        ):
            raise ValueError("automatic requirement effects require evidence")
        return self


class NewRequirementPolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_index: int = Field(ge=0)
    decision: PolicyDecision
    triggered_rule_ids: tuple[RequirementPolicyRule, ...] = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> "NewRequirementPolicyResult":
        if self.decision is not PolicyDecision.REVIEW_REQUIRED:
            raise ValueError("new requirement proposals must require review")
        if len(self.triggered_rule_ids) != len(self.reasons):
            raise ValueError("each new-requirement rule requires one reason")
        if len(self.triggered_rule_ids) != len(set(self.triggered_rule_ids)):
            raise ValueError("new-requirement rule IDs must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("new-requirement evidence IDs must be unique")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("new-requirement reasons must not be blank")
        return self


class RequirementPolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    policy_version: str
    decision: PolicyDecision
    requirement_effects: tuple[RequirementTransitionEffect, ...] = ()
    new_requirement_results: tuple[NewRequirementPolicyResult, ...] = ()
    triggered_rule_ids: tuple[RequirementPolicyRule, ...] = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = ()

    @field_validator("policy_version")
    @classmethod
    def reject_blank_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("policy_version must not be blank")
        return value

    @field_validator("reasons")
    @classmethod
    def reject_blank_result_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not reason.strip() for reason in value):
            raise ValueError("policy reasons must not be blank")
        return value

    @field_validator("triggered_rule_ids", "evidence_ids")
    @classmethod
    def require_unique_result_items(cls, value: tuple) -> tuple:
        if len(value) != len(set(value)):
            raise ValueError("policy result items must be unique")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> "RequirementPolicyResult":
        if len(self.triggered_rule_ids) != len(self.reasons):
            raise ValueError("each policy rule requires one human-readable reason")
        indexes = [item.proposal_index for item in self.new_requirement_results]
        if len(indexes) != len(set(indexes)):
            raise ValueError("new requirement policy results must be unique")
        return self
