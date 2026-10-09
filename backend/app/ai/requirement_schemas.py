from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.schemas import ResolverSourceField
from app.models.enums import RequirementState


class RequirementImpactDisposition(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    UPDATE_PROPOSED = "UPDATE_PROPOSED"


class RequirementCorrectionKind(StrEnum):
    CORRECTION = "CORRECTION"
    RETRACTION = "RETRACTION"


class RequirementSuggestedAction(StrEnum):
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    REQUEST_MISSING_EVIDENCE = "REQUEST_MISSING_EVIDENCE"


class RequirementReconciliationConcernType(StrEnum):
    AMBIGUOUS_REQUIREMENT_MAPPING = "AMBIGUOUS_REQUIREMENT_MAPPING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONDITIONAL_COMPLETION = "CONDITIONAL_COMPLETION"
    EXTRACTION_UNAVAILABLE = "EXTRACTION_UNAVAILABLE"
    POSSIBLE_DUPLICATE_REQUIREMENT = "POSSIBLE_DUPLICATE_REQUIREMENT"


class RequirementSourceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["SOURCE_EXCERPT"] = "SOURCE_EXCERPT"
    correspondence_event_id: UUID
    source_field: ResolverSourceField
    excerpt: str
    attachment_id: UUID | None = None

    @field_validator("excerpt")
    @classmethod
    def reject_blank_excerpt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence excerpt must not be blank")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> "RequirementSourceEvidence":
        is_attachment = self.source_field is ResolverSourceField.ATTACHMENT_TEXT
        if is_attachment != (self.attachment_id is not None):
            raise ValueError("only ATTACHMENT_TEXT evidence requires an attachment_id")
        return self


class ExistingEvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["EXISTING_EVIDENCE"] = "EXISTING_EVIDENCE"
    evidence_item_id: UUID


RequirementEvidenceReference = Annotated[
    RequirementSourceEvidence | ExistingEvidenceReference,
    Field(discriminator="kind"),
]


class ExistingRequirementImpact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: UUID
    disposition: RequirementImpactDisposition
    proposed_state: RequirementState | None = None
    proposed_expected_date: date | None = None
    suggested_action: RequirementSuggestedAction | None = None
    evidence: tuple[RequirementEvidenceReference, ...] = ()
    interpretation: str

    @field_validator("interpretation")
    @classmethod
    def reject_blank_interpretation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("requirement interpretation must not be blank")
        return value

    @model_validator(mode="after")
    def validate_disposition(self) -> "ExistingRequirementImpact":
        if self.proposed_state is RequirementState.RETRACTED:
            raise ValueError("only RETRACTION may withdraw a requirement")
        if self.disposition is RequirementImpactDisposition.NO_CHANGE:
            if self.proposed_state is not None or self.proposed_expected_date is not None:
                raise ValueError("NO_CHANGE cannot contain a proposed state or date")
            return self
        if self.proposed_state is None and self.proposed_expected_date is None:
            raise ValueError("UPDATE_PROPOSED requires a proposed state or date")
        if not self.evidence:
            raise ValueError("UPDATE_PROPOSED requires supporting evidence")
        return self


class NewRequirementProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str | None = None
    expected_date: date | None = None
    evidence: tuple[RequirementEvidenceReference, ...] = Field(min_length=1)
    interpretation: str

    @field_validator("name", "interpretation")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("new requirement text must not be blank")
        return value


class RequirementCorrectionProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RequirementCorrectionKind
    requirement_id: UUID
    previous_state: RequirementState
    previous_expected_date: date | None = None
    target_evidence_item_ids: tuple[UUID, ...] = Field(min_length=1)
    proposed_state: RequirementState | None = None
    proposed_expected_date: date | None = None
    evidence: tuple[RequirementSourceEvidence, ...] = Field(min_length=1)
    interpretation: str

    @field_validator("interpretation")
    @classmethod
    def reject_blank_interpretation(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("correction interpretation must not be blank")
        return value

    @model_validator(mode="after")
    def validate_effect(self) -> "RequirementCorrectionProposal":
        if len(set(self.target_evidence_item_ids)) != len(self.target_evidence_item_ids):
            raise ValueError("target evidence items must be unique")
        if self.proposed_state is RequirementState.RETRACTED:
            raise ValueError("only RETRACTION may withdraw a requirement")
        if self.kind is RequirementCorrectionKind.RETRACTION:
            if self.proposed_state is not None or self.proposed_expected_date is not None:
                raise ValueError("RETRACTION cannot propose a replacement state or date")
        elif self.proposed_state is None and self.proposed_expected_date is None:
            raise ValueError("CORRECTION requires a proposed state or expected date")
        return self


class RequirementReconciliationConcern(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    concern_type: RequirementReconciliationConcernType
    candidate_requirement_ids: tuple[UUID, ...] = ()
    evidence: tuple[RequirementEvidenceReference, ...] = ()
    description: str

    @field_validator("description")
    @classmethod
    def reject_blank_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("concern description must not be blank")
        return value


class RequirementEvidenceConflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_ids: tuple[UUID, ...] = ()
    evidence: tuple[RequirementEvidenceReference, ...] = Field(min_length=2)
    description: str

    @field_validator("description")
    @classmethod
    def reject_blank_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("conflict description must not be blank")
        return value


class RequirementReconciliation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    existing_impacts: tuple[ExistingRequirementImpact, ...] = ()
    new_requirements: tuple[NewRequirementProposal, ...] = ()
    corrections: tuple[RequirementCorrectionProposal, ...] = ()
    concerns: tuple[RequirementReconciliationConcern, ...] = ()
    conflicts: tuple[RequirementEvidenceConflict, ...] = ()

    @model_validator(mode="after")
    def reject_duplicates(self) -> "RequirementReconciliation":
        requirement_ids = [impact.requirement_id for impact in self.existing_impacts]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("existing requirement impacts must be unique")
        normalized_names = [item.name.casefold().strip() for item in self.new_requirements]
        if len(normalized_names) != len(set(normalized_names)):
            raise ValueError("new requirement proposals must be unique")
        correction_ids = [item.requirement_id for item in self.corrections]
        if len(correction_ids) != len(set(correction_ids)):
            raise ValueError("correction targets must be unique")
        if set(correction_ids).intersection(requirement_ids):
            raise ValueError("a requirement cannot have both an impact and a correction")
        return self
