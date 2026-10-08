from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class ReplyDraftGenerationStatus(StrEnum):
    GENERATED_NEW = "GENERATED_NEW"
    EXISTING_ACTIVE_DRAFT = "EXISTING_ACTIVE_DRAFT"


class ReplyDraftGenerationFailureCode(StrEnum):
    NOT_DRAFTABLE = "NOT_DRAFTABLE"
    CONTEXT_OPEN_FAILED = "CONTEXT_OPEN_FAILED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    USAGE_LIMIT_EXCEEDED = "USAGE_LIMIT_EXCEEDED"
    INVALID_GROUNDING = "INVALID_GROUNDING"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


class ReplyDraftGenerationResult(BaseModel):
    """Future S2.3 orchestration result; no send or approval authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ReplyDraftGenerationStatus
    reply_draft_id: UUID
    ai_proposal_id: UUID | None = None

    @model_validator(mode="after")
    def require_proposal_for_new_generation(self) -> "ReplyDraftGenerationResult":
        if self.status is ReplyDraftGenerationStatus.GENERATED_NEW:
            if self.ai_proposal_id is None:
                raise ValueError("a generated draft requires an AI proposal")
        elif self.ai_proposal_id is not None:
            raise ValueError("an existing active draft result has no new AI proposal")
        return self
