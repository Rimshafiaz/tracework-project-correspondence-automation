from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import ReplyDraftStatus, ReplyType


class ReplyDraftContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    body: str

    @field_validator("subject", "body")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ReplyDraftSnapshot(BaseModel):
    """Persisted reply-draft facts, suitable for later authenticated APIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    follow_up_id: UUID
    project_id: UUID
    requirement_id: UUID
    ai_proposal_id: UUID | None
    source_correspondence_event_id: UUID | None
    target_correspondence_event_id: UUID | None
    project_contact_id: UUID | None
    reply_type: ReplyType
    generated: ReplyDraftContent
    edited: ReplyDraftContent | None
    effective: ReplyDraftContent
    status: ReplyDraftStatus
    recipient_email: str | None
    gmail_thread_id: str | None
    source_gmail_message_id: str | None
    approved_at: datetime | None
    approved_by_subject: str | None
    rejected_at: datetime | None
    send_attempt_id: UUID | None
    send_attempted_at: datetime | None
    send_failure_code: str | None
    sent_at: datetime | None
    gmail_message_id: str | None
    gmail_sent_thread_id: str | None
    can_edit: bool
    can_approve: bool
    can_reject: bool
    can_send: bool
    can_retry_send: bool
    send_attention_required: bool
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
