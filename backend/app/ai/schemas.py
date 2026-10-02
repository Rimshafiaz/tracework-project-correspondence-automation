from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidateSet
from app.models.enums import AttachmentProcessingState


class ResolutionStatus(StrEnum):
    MATCHED = "MATCHED"
    MULTI_PROJECT = "MULTI_PROJECT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_MATCH = "NO_MATCH"


class ResolutionConcern(StrEnum):
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MULTI_PROJECT_SCOPE_UNCLEAR = "MULTI_PROJECT_SCOPE_UNCLEAR"
    NO_PLAUSIBLE_CANDIDATE = "NO_PLAUSIBLE_CANDIDATE"


class ResolverSourceField(StrEnum):
    SUBJECT = "SUBJECT"
    BODY = "BODY"
    ATTACHMENT_TEXT = "ATTACHMENT_TEXT"


class ResolverCorrespondence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    source: str
    external_conversation_id: str | None = None
    sender_identifier: str
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    body: str
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return value


class ResolverAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: UUID
    filename: str
    mime_type: str
    processing_state: AttachmentProcessingState
    extracted_text: str | None = None
    extraction_metadata: dict[str, object] | None = None


class ProjectResolverInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence: ResolverCorrespondence
    candidates: ProjectCandidateSet
    attachments: tuple[ResolverAttachment, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_or_unrelated_attachments(self) -> "ProjectResolverInput":
        attachment_ids = [attachment.attachment_id for attachment in self.attachments]
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError("resolver attachments must be unique")
        candidate_attachment_ids = {
            signal.attachment_id
            for candidate in self.candidates.candidates
            for signal in candidate.signals
            if signal.attachment_id is not None
        }
        if not candidate_attachment_ids.issubset(set(attachment_ids)):
            raise ValueError("candidate signals must reference supplied attachments")
        return self


class CandidateSignalReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    signal_type: CandidateSignalType
    matched_value: str
    source: CandidateSignalSource
    identifier_type: str | None = None
    source_record_id: UUID | None = None
    attachment_id: UUID | None = None
    evidence_item_id: UUID | None = None


class SourceTextEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    source_field: ResolverSourceField
    excerpt: str
    attachment_id: UUID | None = None

    @field_validator("excerpt")
    @classmethod
    def reject_blank_excerpt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence excerpt must not be blank")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> "SourceTextEvidence":
        is_attachment = self.source_field is ResolverSourceField.ATTACHMENT_TEXT
        if is_attachment != (self.attachment_id is not None):
            raise ValueError(
                "only ATTACHMENT_TEXT evidence requires an attachment_id"
            )
        return self


class ResolutionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    signal_references: tuple[CandidateSignalReference, ...] = ()
    source_evidence: tuple[SourceTextEvidence, ...] = ()
    interpretation: str

    @field_validator("interpretation")
    @classmethod
    def reject_blank_interpretation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence interpretation must not be blank")
        return value

    @model_validator(mode="after")
    def require_support(self) -> "ResolutionEvidence":
        if not self.signal_references and not self.source_evidence:
            raise ValueError("resolution evidence requires a signal or source excerpt")
        if any(
            reference.project_id != self.project_id
            for reference in self.signal_references
        ):
            raise ValueError("signal references must support the evidence project")
        return self


class EvidenceConflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_ids: tuple[UUID, ...] = Field(min_length=1)
    signal_references: tuple[CandidateSignalReference, ...] = ()
    source_evidence: tuple[SourceTextEvidence, ...] = ()
    description: str

    @field_validator("description")
    @classmethod
    def reject_blank_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("conflict description must not be blank")
        return value

    @model_validator(mode="after")
    def require_conflicting_support(self) -> "EvidenceConflict":
        if len(self.signal_references) + len(self.source_evidence) < 2:
            raise ValueError("a conflict requires at least two evidence references")
        return self


class ProjectResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ResolutionStatus
    project_ids: tuple[UUID, ...] = ()
    evidence: tuple[ResolutionEvidence, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    concerns: tuple[ResolutionConcern, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> "ProjectResolution":
        unique_project_ids = set(self.project_ids)
        if len(unique_project_ids) != len(self.project_ids):
            raise ValueError("resolved project IDs must be unique")
        if self.status is ResolutionStatus.MATCHED and len(self.project_ids) != 1:
            raise ValueError("MATCHED requires exactly one project")
        if self.status is ResolutionStatus.MULTI_PROJECT and len(self.project_ids) < 2:
            raise ValueError("MULTI_PROJECT requires at least two projects")
        if self.status is ResolutionStatus.REVIEW_REQUIRED and not self.project_ids:
            raise ValueError("REVIEW_REQUIRED requires at least one plausible project")
        if self.status is ResolutionStatus.NO_MATCH:
            if self.project_ids or self.evidence or self.conflicts:
                raise ValueError("NO_MATCH cannot select projects or contain evidence")
            if ResolutionConcern.NO_PLAUSIBLE_CANDIDATE not in self.concerns:
                raise ValueError("NO_MATCH requires NO_PLAUSIBLE_CANDIDATE")
            return self

        evidenced_project_ids = {item.project_id for item in self.evidence}
        if not unique_project_ids.issubset(evidenced_project_ids):
            raise ValueError("every resolved project requires supporting evidence")
        return self
