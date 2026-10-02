from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.models.enums import ProjectStatus


class CandidateSignalSource(StrEnum):
    CORRESPONDENCE_EVENT = "CORRESPONDENCE_EVENT"
    ATTACHMENT = "ATTACHMENT"
    EVIDENCE_ITEM = "EVIDENCE_ITEM"
    PROJECT_RECORD = "PROJECT_RECORD"
    APPROVED_CONVERSATION_LINK = "APPROVED_CONVERSATION_LINK"


class CandidateSignalType(StrEnum):
    PROJECT_CODE = "PROJECT_CODE"
    VERIFIED_IDENTIFIER = "VERIFIED_IDENTIFIER"
    NORMALIZED_NAME = "NORMALIZED_NAME"
    ALIAS = "ALIAS"
    PROJECT_CONTACT = "PROJECT_CONTACT"
    APPROVED_CONVERSATION = "APPROVED_CONVERSATION"
    DOCUMENT_IDENTIFIER = "DOCUMENT_IDENTIFIER"
    FUZZY_NAME = "FUZZY_NAME"
    FUZZY_ALIAS = "FUZZY_ALIAS"


class CandidateSetCardinality(StrEnum):
    NONE = "NONE"
    SINGLE = "SINGLE"
    MULTIPLE = "MULTIPLE"


class FuzzyCandidateOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_score: float = Field(
        ge=0,
        le=100,
        description="Retrieval filter only; never authorizes a state mutation.",
    )
    max_candidates_per_hint: int = Field(gt=0)


class CandidateValueHint(BaseModel):
    model_config = ConfigDict(frozen=True)

    normalized_value: str
    source: CandidateSignalSource
    attachment_id: UUID | None = None
    evidence_item_id: UUID | None = None

    @field_validator("normalized_value")
    @classmethod
    def reject_blank_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("normalized_value must not be blank")
        return value


class CandidateIdentifierHint(CandidateValueHint):
    identifier_type: str

    @field_validator("identifier_type")
    @classmethod
    def reject_blank_identifier_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identifier_type must not be blank")
        return value

    @model_validator(mode="after")
    def require_document_provenance(self) -> "CandidateIdentifierHint":
        if (
            self.source is CandidateSignalSource.ATTACHMENT
            and self.attachment_id is None
        ):
            raise ValueError("attachment identifier hints require attachment_id")
        if (
            self.source is CandidateSignalSource.EVIDENCE_ITEM
            and self.evidence_item_id is None
        ):
            raise ValueError("evidence identifier hints require evidence_item_id")
        return self


class ProjectCandidateQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    external_conversation_id: str | None = None
    sender_email_normalized: str | None = None
    project_codes: tuple[CandidateValueHint, ...] = ()
    normalized_names: tuple[CandidateValueHint, ...] = ()
    identifiers: tuple[CandidateIdentifierHint, ...] = ()

    @field_validator("source")
    @classmethod
    def reject_blank_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source must not be blank")
        return value

    @field_validator("external_conversation_id", "sender_email_normalized")
    @classmethod
    def reject_blank_optional_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("optional identity values must not be blank")
        return value

    @field_validator("sender_email_normalized")
    @classmethod
    def normalize_sender_email(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None


class ProjectCandidateSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_type: CandidateSignalType
    matched_value: str
    source: CandidateSignalSource
    identifier_type: str | None = None
    source_record_id: UUID | None = None
    attachment_id: UUID | None = None
    evidence_item_id: UUID | None = None
    exact: bool
    verified: bool = False
    previously_approved: bool = False
    similarity_score: float | None = Field(default=None, ge=0, le=100)

    @field_validator("matched_value")
    @classmethod
    def reject_blank_match(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("matched_value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_signal_semantics(self) -> "ProjectCandidateSignal":
        fuzzy = self.signal_type in {
            CandidateSignalType.FUZZY_NAME,
            CandidateSignalType.FUZZY_ALIAS,
        }
        if fuzzy != (self.similarity_score is not None):
            raise ValueError("only fuzzy signals require a similarity score")
        if fuzzy and self.exact:
            raise ValueError("fuzzy signals cannot be exact")
        if not fuzzy and not self.exact:
            raise ValueError("deterministic signals must be exact")
        if self.signal_type is CandidateSignalType.VERIFIED_IDENTIFIER and not self.verified:
            raise ValueError("verified identifier signals must be marked verified")
        if (
            self.signal_type is CandidateSignalType.APPROVED_CONVERSATION
            and not self.previously_approved
        ):
            raise ValueError("approved conversation signals must be marked previously approved")
        return self


class ProjectCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    project_code: str
    project_name: str
    project_status: ProjectStatus
    signals: tuple[ProjectCandidateSignal, ...] = Field(min_length=1)

    @field_validator("project_code", "project_name")
    @classmethod
    def reject_blank_project_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("project identity must not be blank")
        return value


class ProjectCandidateSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: tuple[ProjectCandidate, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_projects(self) -> "ProjectCandidateSet":
        project_ids = [candidate.project_id for candidate in self.candidates]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("candidate projects must be unique")
        return self

    @computed_field
    @property
    def cardinality(self) -> CandidateSetCardinality:
        if not self.candidates:
            return CandidateSetCardinality.NONE
        if len(self.candidates) == 1:
            return CandidateSetCardinality.SINGLE
        return CandidateSetCardinality.MULTIPLE

    @computed_field
    @property
    def is_ambiguous(self) -> bool:
        return len(self.candidates) > 1
