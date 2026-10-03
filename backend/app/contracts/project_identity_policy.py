from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.schemas import ProjectResolution, ResolutionStatus
from app.contracts.project_candidate import ProjectCandidateSet
from app.models.enums import PolicyDecision, ProposalType


class ProjectIdentityRule(StrEnum):
    PROPOSAL_TYPE_INVALID = "PID-001-PROPOSAL-TYPE-INVALID"
    CANDIDATE_SNAPSHOT_MISSING = "PID-002-CANDIDATE-SNAPSHOT-MISSING"
    RESOLUTION_INTEGRITY_FAILED = "PID-003-RESOLUTION-INTEGRITY-FAILED"
    EVIDENCE_NOT_CURRENTLY_VALID = "PID-004-EVIDENCE-NOT-CURRENTLY-VALID"
    PROVENANCE_UNVERIFIED = "PID-005-PROVENANCE-UNVERIFIED"

    NO_MATCH = "PID-100-NO-MATCH"
    RESOLVER_REVIEW_REQUIRED = "PID-101-RESOLVER-REVIEW-REQUIRED"
    RESOLVER_REPORTED_CONFLICT = "PID-102-RESOLVER-REPORTED-CONFLICT"

    APPROVED_CONVERSATION_LINK = "PID-200-APPROVED-CONVERSATION-LINK"
    EXACT_PROJECT_CODE = "PID-201-EXACT-PROJECT-CODE"
    EXACT_VERIFIED_IDENTIFIER = "PID-202-EXACT-VERIFIED-IDENTIFIER"
    EXACT_DOCUMENT_IDENTIFIER = "PID-203-EXACT-DOCUMENT-IDENTIFIER"
    KNOWN_PROJECT_CONTACT = "PID-204-KNOWN-PROJECT-CONTACT"

    KNOWN_CONTACT_ONLY = "PID-300-KNOWN-CONTACT-ONLY"
    NORMALIZED_NAME_ONLY = "PID-301-NORMALIZED-NAME-ONLY"
    ALIAS_ONLY = "PID-302-ALIAS-ONLY"
    FUZZY_MATCH_ONLY = "PID-303-FUZZY-MATCH-ONLY"
    SEMANTIC_INTERPRETATION_ONLY = "PID-304-SEMANTIC-INTERPRETATION-ONLY"
    UNKNOWN_OR_UNTRUSTED_SENDER = "PID-305-UNKNOWN-OR-UNTRUSTED-SENDER"
    INSUFFICIENT_INDEPENDENT_IDENTITY = "PID-306-INSUFFICIENT-INDEPENDENT-IDENTITY"

    AUTO_APPROVED_CONVERSATION = "PID-400-AUTO-APPROVED-CONVERSATION"
    AUTO_PROJECT_CODE_AND_CONTACT = "PID-401-AUTO-PROJECT-CODE-AND-CONTACT"
    AUTO_VERIFIED_IDENTIFIER_AND_CONTACT = (
        "PID-402-AUTO-VERIFIED-IDENTIFIER-AND-CONTACT"
    )

    SAME_TYPE_DIFFERENT_VALUES = "PID-500-SAME-TYPE-DIFFERENT-VALUES"
    SAME_IDENTIFIER_MULTIPLE_PROJECTS = (
        "PID-501-SAME-IDENTIFIER-MULTIPLE-PROJECTS"
    )
    BODY_ATTACHMENT_IDENTITY_CONFLICT = (
        "PID-502-BODY-ATTACHMENT-IDENTITY-CONFLICT"
    )
    CONVERSATION_IDENTIFIER_CONFLICT = (
        "PID-503-CONVERSATION-IDENTIFIER-CONFLICT"
    )

    MULTI_PROJECT_AUTO_ELIGIBLE = "PID-600-MULTI-PROJECT-AUTO-ELIGIBLE"
    MULTI_PROJECT_EVIDENCE_INCOMPLETE = (
        "PID-601-MULTI-PROJECT-EVIDENCE-INCOMPLETE"
    )
    MULTI_PROJECT_SCOPE_UNCLEAR = "PID-602-MULTI-PROJECT-SCOPE-UNCLEAR"
    MULTI_PROJECT_PARTIAL_TRUST = "PID-603-MULTI-PROJECT-PARTIAL-TRUST"


class ProjectIdentityPolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    correspondence_event_id: UUID
    proposal_type: ProposalType
    resolution: ProjectResolution
    candidate_set: ProjectCandidateSet
    proposal_evidence_ids: tuple[UUID, ...] = ()
    invalidated_evidence_ids: tuple[UUID, ...] = ()
    validated_source_record_ids: tuple[UUID, ...] = ()

    @field_validator(
        "proposal_evidence_ids",
        "invalidated_evidence_ids",
        "validated_source_record_ids",
    )
    @classmethod
    def require_unique_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("policy context IDs must be unique")
        return value


class ProjectIdentityPolicyResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    resolver_status: ResolutionStatus
    policy_version: str
    decision: PolicyDecision
    triggered_rule_ids: tuple[ProjectIdentityRule, ...] = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = ()

    @field_validator("policy_version")
    @classmethod
    def reject_blank_policy_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("policy_version must not be blank")
        return value

    @field_validator("reasons")
    @classmethod
    def reject_blank_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
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
    def require_reason_for_each_rule(self) -> "ProjectIdentityPolicyResult":
        if len(self.triggered_rule_ids) != len(self.reasons):
            raise ValueError("each triggered policy rule requires one reason")
        return self
