from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ReplyType


class ReplyDraftGroundingReferenceType(StrEnum):
    FOLLOW_UP = "FOLLOW_UP"
    PROJECT = "PROJECT"
    REQUIREMENT = "REQUIREMENT"
    EVIDENCE = "EVIDENCE"
    CORRESPONDENCE = "CORRESPONDENCE"
    DOCUMENT = "DOCUMENT"


class ReplyDraftGroundingReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference_type: ReplyDraftGroundingReferenceType
    record_id: UUID


class ReplyDraftProposal(BaseModel):
    """Strict model-proposed content; delivery and targeting remain application-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reply_type: ReplyType
    subject: str
    body: str
    grounding_references: tuple[ReplyDraftGroundingReference, ...] = Field(
        min_length=1
    )

    @field_validator("subject", "body")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
