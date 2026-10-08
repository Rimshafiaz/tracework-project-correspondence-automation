from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    DocumentFilingStatus,
    DocumentRevisionStatus,
    EvidenceValidity,
    FollowUpCancelReason,
    FollowUpPurpose,
    FollowUpStatus,
    ProjectStatus,
    RequirementState,
)


class ReplyDraftEligibilityStatus(StrEnum):
    DRAFTABLE = "DRAFTABLE"
    NOT_DRAFTABLE_IN_S2_V1 = "NOT_DRAFTABLE_IN_S2_V1"


class ReplyDraftEligibilityReason(StrEnum):
    FOLLOW_UP_NOT_DUE = "FOLLOW_UP_NOT_DUE"
    MISSING_AUTHORITATIVE_LINEAGE = "MISSING_AUTHORITATIVE_LINEAGE"
    MISSING_SOURCE_CORRESPONDENCE = "MISSING_SOURCE_CORRESPONDENCE"
    INCONSISTENT_LINEAGE = "INCONSISTENT_LINEAGE"
    NO_AUTHORITATIVE_PROJECT_LINK = "NO_AUTHORITATIVE_PROJECT_LINK"
    SOURCE_PROJECT_MISMATCH = "SOURCE_PROJECT_MISMATCH"
    SENDER_NOT_ACTIVE_TRUSTED_CONTACT = "SENDER_NOT_ACTIVE_TRUSTED_CONTACT"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    MISSING_GMAIL_SOURCE_METADATA = "MISSING_GMAIL_SOURCE_METADATA"


class ReplyDraftReadLimits(BaseModel):
    """Bounded S2.2 read limits; later scoped reads must use these values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_evidence_items: int = Field(default=12, gt=0)
    max_recent_correspondence: int = Field(default=8, gt=0)
    max_correspondence_body_characters: int = Field(default=4000, gt=0)
    max_evidence_excerpt_characters: int = Field(default=2000, gt=0)
    max_follow_up_history: int = Field(default=12, gt=0)
    max_document_statuses: int = Field(default=12, gt=0)


class FollowUpReplyScope(BaseModel):
    """Derived authoritative scope. It is never accepted from a model caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    follow_up_id: UUID
    project_id: UUID
    requirement_id: UUID
    source_correspondence_event_id: UUID
    trusted_contact_id: UUID
    gmail_message_id: str
    gmail_thread_id: str
    originating_state_transition_id: UUID | None = None
    originating_audit_event_id: UUID | None = None

    @field_validator("gmail_message_id", "gmail_thread_id")
    @classmethod
    def require_nonblank_gmail_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Gmail identifier must not be blank")
        return value

    @model_validator(mode="after")
    def require_one_authoritative_origin(self) -> "FollowUpReplyScope":
        if (self.originating_state_transition_id is None) == (
            self.originating_audit_event_id is None
        ):
            raise ValueError("reply scope requires exactly one authoritative origin")
        return self


class ReplyDraftEligibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ReplyDraftEligibilityStatus
    reason: ReplyDraftEligibilityReason | None = None
    scope: FollowUpReplyScope | None = None

    @model_validator(mode="after")
    def require_consistent_result(self) -> "ReplyDraftEligibility":
        if self.status is ReplyDraftEligibilityStatus.DRAFTABLE:
            if self.reason is not None or self.scope is None:
                raise ValueError("a draftable result requires scope and no rejection reason")
        elif self.reason is None or self.scope is not None:
            raise ValueError("a non-draftable result requires a reason and no scope")
        return self


class ScopedReplyProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    project_code: str
    name: str
    status: ProjectStatus


class ScopedReplyEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    correspondence_event_id: UUID
    attachment_id: UUID | None
    source_type: str
    excerpt: str
    excerpt_truncated: bool
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None
    validity: EvidenceValidity
    is_untrusted_source_data: Literal[True] = True


class ScopedReplyRequirementContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: UUID
    project_id: UUID
    name: str
    description: str | None
    state: RequirementState
    expected_date: date | None
    evidence: tuple[ScopedReplyEvidence, ...]
    evidence_limit_reached: bool


class ScopedReplyCorrespondence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    source: str
    external_message_id: str
    external_conversation_id: str | None
    sender_identifier: str
    sender_email: str | None
    sender_name: str | None
    received_at: datetime
    subject: str | None
    body: str
    body_truncated: bool
    is_untrusted_source_data: Literal[True] = True


class ScopedReplyRecentCorrespondence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence: tuple[ScopedReplyCorrespondence, ...]
    limit_reached: bool


class ScopedReplyFollowUpHistoryItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    follow_up_id: UUID
    purpose: FollowUpPurpose
    reason: str
    expected_date: date
    due_on: date
    status: FollowUpStatus
    became_due_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: FollowUpCancelReason | None
    completed_at: datetime | None


class ScopedReplyFollowUpHistory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    follow_ups: tuple[ScopedReplyFollowUpHistoryItem, ...]
    limit_reached: bool


class ScopedReplyDocumentRevisionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    source_attachment_id: UUID
    filename: str
    category: str
    filing_status: DocumentFilingStatus
    document_family_key: str | None
    revision_label: str | None
    revision_normalized: str | None
    revision_order: int | None
    revision_status: DocumentRevisionStatus
    revision_decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScopedReplyDocumentRevisionStatuses(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[ScopedReplyDocumentRevisionStatus, ...]
    limit_reached: bool
