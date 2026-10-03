import hashlib
import json
from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.ai.schemas import ResolverAttachment, ResolverCorrespondence
from app.models.enums import EvidenceValidity, RequirementState

REQUIREMENT_CONTEXT_SNAPSHOT_SCHEMA_VERSION = 1
REQUIREMENT_CONTEXT_SNAPSHOT_KEY = "requirement_reconciliation_context"
REQUIREMENT_CONTEXT_SNAPSHOT_VERSION_KEY = "requirement_context_snapshot_schema_version"


class RequirementContextSnapshotError(ValueError):
    pass


class RequirementContextLimitKind(StrEnum):
    REQUIREMENT_COUNT = "REQUIREMENT_COUNT"
    ATTACHMENT_COUNT = "ATTACHMENT_COUNT"
    SOURCE_CHARACTER_COUNT = "SOURCE_CHARACTER_COUNT"


class RequirementContextLimitOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_kind: RequirementContextLimitKind
    configured_limit: int = Field(gt=0)
    actual_value: int = Field(gt=0)
    reason: str

    @field_validator("reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("context-limit reason must not be blank")
        return value

    @model_validator(mode="after")
    def require_exceeded_limit(self) -> "RequirementContextLimitOutcome":
        if self.actual_value <= self.configured_limit:
            raise ValueError("actual context size must exceed the configured limit")
        return self


class RequirementAttachmentContext(ResolverAttachment):
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RequirementSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: UUID
    name: str
    description: str | None = None
    current_state: RequirementState
    expected_date: date | None = None

    @field_validator("name")
    @classmethod
    def reject_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("requirement name must not be blank")
        return value


class ExistingRequirementEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    correspondence_event_id: UUID
    project_id: UUID
    requirement_id: UUID | None = None
    attachment_id: UUID | None = None
    source_type: str
    excerpt: str
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None
    validity: EvidenceValidity

    @field_validator("source_type", "excerpt")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence text fields must not be blank")
        return value

    @model_validator(mode="after")
    def require_valid_evidence(self) -> "ExistingRequirementEvidence":
        if self.validity is not EvidenceValidity.VALID:
            raise ValueError("reconciler context may contain only valid evidence")
        return self


class RequirementReconcilerInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    authoritative_project_link_id: UUID
    correspondence: ResolverCorrespondence
    requirements: tuple[RequirementSnapshot, ...]
    attachments: tuple[RequirementAttachmentContext, ...] = ()
    existing_valid_evidence: tuple[ExistingRequirementEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_context(self) -> "RequirementReconcilerInput":
        requirement_ids = [item.requirement_id for item in self.requirements]
        attachment_ids = [item.attachment_id for item in self.attachments]
        evidence_ids = [item.evidence_item_id for item in self.existing_valid_evidence]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirements must be unique")
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError("attachments must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("existing evidence must be unique")

        known_requirement_ids = set(requirement_ids)
        for evidence in self.existing_valid_evidence:
            if evidence.project_id != self.project_id:
                raise ValueError("existing evidence must belong to the resolved project")
            if (
                evidence.requirement_id is not None
                and evidence.requirement_id not in known_requirement_ids
            ):
                raise ValueError("existing evidence must reference a supplied requirement")
        return self


class RequirementAttachmentSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: UUID
    processing_state: str
    content_hash: str | None = None
    extracted_text_sha256: str | None = None
    extraction_metadata_sha256: str | None = None


class RequirementEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    project_id: UUID
    requirement_id: UUID | None = None
    validity: EvidenceValidity
    excerpt_sha256: str


class RequirementContextSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    authoritative_project_link_id: UUID
    correspondence_event_id: UUID
    subject_sha256: str | None = None
    body_sha256: str
    requirements: tuple[RequirementSnapshot, ...]
    attachments: tuple[RequirementAttachmentSnapshot, ...] = ()
    existing_evidence: tuple[RequirementEvidenceSnapshot, ...] = ()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def serialize_requirement_context_snapshot(
    context: RequirementReconcilerInput,
) -> dict[str, object]:
    snapshot = RequirementContextSnapshot(
        project_id=context.project_id,
        authoritative_project_link_id=context.authoritative_project_link_id,
        correspondence_event_id=context.correspondence.correspondence_event_id,
        subject_sha256=(
            _sha256(context.correspondence.subject)
            if context.correspondence.subject is not None
            else None
        ),
        body_sha256=_sha256(context.correspondence.body),
        requirements=context.requirements,
        attachments=tuple(
            RequirementAttachmentSnapshot(
                attachment_id=attachment.attachment_id,
                processing_state=attachment.processing_state.value,
                content_hash=attachment.content_hash,
                extracted_text_sha256=(
                    _sha256(attachment.extracted_text)
                    if attachment.extracted_text is not None
                    else None
                ),
                extraction_metadata_sha256=(
                    _sha256(
                        json.dumps(
                            attachment.extraction_metadata,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                    if attachment.extraction_metadata is not None
                    else None
                ),
            )
            for attachment in context.attachments
        ),
        existing_evidence=tuple(
            RequirementEvidenceSnapshot(
                evidence_item_id=evidence.evidence_item_id,
                project_id=evidence.project_id,
                requirement_id=evidence.requirement_id,
                validity=evidence.validity,
                excerpt_sha256=_sha256(evidence.excerpt),
            )
            for evidence in context.existing_valid_evidence
        ),
    )
    return {
        REQUIREMENT_CONTEXT_SNAPSHOT_VERSION_KEY: (
            REQUIREMENT_CONTEXT_SNAPSHOT_SCHEMA_VERSION
        ),
        REQUIREMENT_CONTEXT_SNAPSHOT_KEY: snapshot.model_dump(mode="json"),
    }


def reconstruct_requirement_context_snapshot(
    input_metadata: dict[str, object] | None,
) -> RequirementContextSnapshot:
    if input_metadata is None:
        raise RequirementContextSnapshotError("requirement context snapshot is missing")
    if (
        input_metadata.get(REQUIREMENT_CONTEXT_SNAPSHOT_VERSION_KEY)
        != REQUIREMENT_CONTEXT_SNAPSHOT_SCHEMA_VERSION
    ):
        raise RequirementContextSnapshotError(
            "requirement context snapshot schema version is missing or unsupported"
        )
    payload = input_metadata.get(REQUIREMENT_CONTEXT_SNAPSHOT_KEY)
    if not isinstance(payload, dict):
        raise RequirementContextSnapshotError(
            "requirement context snapshot payload is missing or malformed"
        )
    try:
        return RequirementContextSnapshot.model_validate(payload)
    except ValidationError as exc:
        raise RequirementContextSnapshotError(
            "requirement context snapshot payload is invalid"
        ) from exc
