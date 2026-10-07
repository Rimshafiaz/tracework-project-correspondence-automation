from enum import StrEnum

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DOCUMENT_REVISION_POLICY_VERSION = "document-revision/1"

# Revision order is intended for a PostgreSQL INTEGER column in Step 19.2.
MAX_REVISION_ORDER = 2_147_483_647


class RevisionParseStatus(StrEnum):
    PARSED = "PARSED"
    NO_REVISION = "NO_REVISION"
    UNSUPPORTED = "UNSUPPORTED"


class RevisionParseReason(StrEnum):
    NO_REVISION_LABEL = "NO_REVISION_LABEL"
    UNSUPPORTED_REVISION_LABEL = "UNSUPPORTED_REVISION_LABEL"
    BLANK_DOCUMENT_FAMILY = "BLANK_DOCUMENT_FAMILY"
    REVISION_OUT_OF_RANGE = "REVISION_OUT_OF_RANGE"


class RevisionOutcome(StrEnum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    DUPLICATE = "DUPLICATE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class DocumentRevisionRule(StrEnum):
    SUPPORTED_NUMERIC_REVISION = "DREV-001-SUPPORTED-NUMERIC-REVISION"
    FIRST_REVISION_CURRENT = "DREV-100-FIRST-REVISION-CURRENT"
    NEWER_REVISION_CURRENT = "DREV-101-NEWER-REVISION-CURRENT"
    OLDER_REVISION_HISTORICAL = "DREV-102-OLDER-REVISION-HISTORICAL"
    SAME_REVISION_SAME_CONTENT_DUPLICATE = (
        "DREV-103-SAME-REVISION-SAME-CONTENT-DUPLICATE"
    )
    SAME_REVISION_DIFFERENT_CONTENT_REVIEW = (
        "DREV-200-SAME-REVISION-DIFFERENT-CONTENT-REVIEW"
    )
    UNSUPPORTED_REVISION_REVIEW = "DREV-201-UNSUPPORTED-REVISION-REVIEW"
    MISSING_REVISION_REVIEW = "DREV-202-MISSING-REVISION-REVIEW"
    FAMILY_UNASSESSED_REVIEW = "DREV-203-FAMILY-UNASSESSED-REVIEW"


class DocumentRevisionParseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    original_filename: str
    filename_stem: str
    status: RevisionParseStatus
    family_key: str | None = None
    raw_revision: str | None = None
    normalized_revision: str | None = None
    revision_order: int | None = None
    reason: RevisionParseReason | None = None

    @field_validator("original_filename")
    @classmethod
    def reject_blank_filename(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_filename must not be blank")
        return value

    @model_validator(mode="after")
    def enforce_parse_shape(self) -> "DocumentRevisionParseResult":
        parsed_values = (
            self.family_key,
            self.raw_revision,
            self.normalized_revision,
            self.revision_order,
        )
        if self.status is RevisionParseStatus.PARSED:
            if any(value is None for value in parsed_values):
                raise ValueError("parsed revisions require complete normalized values")
            if self.reason is not None:
                raise ValueError("parsed revisions must not include a failure reason")
        elif any(value is not None for value in parsed_values):
            raise ValueError("non-parsed revisions must not include normalized values")
        elif self.reason is None:
            raise ValueError("non-parsed revisions require a reason")
        return self


class DocumentRevisionEffect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    source_attachment_id: UUID
    project_id: UUID
    category: str
    family_key: str | None
    raw_revision_label: str | None
    normalized_revision: str | None
    revision_order: int | None
    previous_current_document_id: UUID | None = None
    previous_current_revision: str | None = None
    incoming_outcome: RevisionOutcome
    old_current_outcome: RevisionOutcome | None = None
    policy_version: str
    triggered_rule_ids: tuple[DocumentRevisionRule, ...] = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)

    @field_validator("category", "policy_version")
    @classmethod
    def reject_blank_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("revision effect text must not be blank")
        return value

    @model_validator(mode="after")
    def enforce_effect_integrity(self) -> "DocumentRevisionEffect":
        if len(self.triggered_rule_ids) != len(self.reasons):
            raise ValueError("each revision rule requires one readable reason")
        if len(set(self.triggered_rule_ids)) != len(self.triggered_rule_ids):
            raise ValueError("revision effect rules must be unique")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("revision effect reasons must not be blank")
        parsed = (
            self.family_key,
            self.raw_revision_label,
            self.normalized_revision,
            self.revision_order,
        )
        if self.incoming_outcome is not RevisionOutcome.REVIEW_REQUIRED and any(
            value is None for value in parsed
        ):
            raise ValueError("automatic revision outcomes require parsed metadata")
        if self.old_current_outcome is not None and (
            self.previous_current_document_id is None
            or self.old_current_outcome is not RevisionOutcome.HISTORICAL
        ):
            raise ValueError("an old current effect must identify a historical document")
        return self


class DocumentRevisionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    state_transition_id: UUID
    review_item_id: UUID | None = None
    outcome: RevisionOutcome
    policy_version: str
    triggered_rule_ids: tuple[DocumentRevisionRule, ...] = Field(min_length=1)
