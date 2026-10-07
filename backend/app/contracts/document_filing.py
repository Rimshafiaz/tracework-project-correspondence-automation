from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


DOCUMENT_FILING_ENTITY_TYPE = "document_filing"


class DocumentFilingAuthorization(StrEnum):
    AUTOMATIC_PROJECT_POLICY = "AUTOMATIC_PROJECT_POLICY"
    HUMAN_PROJECT_REVIEW = "HUMAN_PROJECT_REVIEW"


class DocumentFilingEffect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    attachment_id: UUID
    project_id: UUID
    filename: str
    category: str
    content_hash: str
    authorization: DocumentFilingAuthorization

    @field_validator("filename", "category", "content_hash")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("document filing values must not be blank")
        return value


class DriveFileRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_id: str
    name: str
    parent_folder_id: str

    @field_validator("file_id", "name", "parent_folder_id")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Drive file values must not be blank")
        return value


class DocumentFilingSkipReason(StrEnum):
    NO_ATTACHMENTS = "NO_ATTACHMENTS"
    PROJECT_NOT_AUTHORIZED = "PROJECT_NOT_AUTHORIZED"
    PROJECT_REVIEW_PENDING = "PROJECT_REVIEW_PENDING"
    PROJECT_REVIEW_REJECTED = "PROJECT_REVIEW_REJECTED"
    MULTI_PROJECT_ATTACHMENT_AMBIGUOUS = "MULTI_PROJECT_ATTACHMENT_AMBIGUOUS"
    ATTACHMENT_PROJECT_CONFLICT = "ATTACHMENT_PROJECT_CONFLICT"
    ATTACHMENT_CONTENT_UNAVAILABLE = "ATTACHMENT_CONTENT_UNAVAILABLE"
    ATTACHMENT_CONTENT_MISMATCH = "ATTACHMENT_CONTENT_MISMATCH"


class DocumentFilingOutcomeStatus(StrEnum):
    FILED = "FILED"
    ALREADY_FILED = "ALREADY_FILED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    SKIPPED = "SKIPPED"


class DocumentFilingOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: UUID
    project_id: UUID | None = None
    document_id: UUID | None = None
    state_transition_id: UUID | None = None
    status: DocumentFilingOutcomeStatus
    skip_reason: DocumentFilingSkipReason | None = None
    failure_code: str | None = None


class CorrespondenceDocumentFilingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    outcomes: tuple[DocumentFilingOutcome, ...] = ()
