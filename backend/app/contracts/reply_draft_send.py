from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReplyDraftSendStatus(StrEnum):
    SENT_NOW = "SENT_NOW"
    RECONCILED_SENT = "RECONCILED_SENT"
    ALREADY_SENT = "ALREADY_SENT"
    SEND_STILL_PENDING = "SEND_STILL_PENDING"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    AMBIGUOUS_RECOVERY = "AMBIGUOUS_RECOVERY"
    ACTION_REQUIRED = "ACTION_REQUIRED"


class ReplyDraftSendResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ReplyDraftSendStatus
    reply_draft_id: UUID
    gmail_message_id: str | None = None
    gmail_thread_id: str | None = None
    failure_code: str | None = None


class ReplyDraftSendOwnership(StrEnum):
    SEND_OWNER = "SEND_OWNER"
    EXISTING_PENDING_ATTEMPT = "EXISTING_PENDING_ATTEMPT"
    ALREADY_SENT = "ALREADY_SENT"
