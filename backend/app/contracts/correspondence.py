from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class NormalizedAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)

    @field_validator("source_attachment_id", "filename", "mime_type")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class NormalizedCorrespondenceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    external_event_id: str
    external_conversation_id: str | None = None
    sender_identifier: str
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    body: str
    received_at: datetime
    attachments: tuple[NormalizedAttachment, ...] = ()
    source_metadata: dict[str, JsonValue] | None = None

    @field_validator("source", "external_event_id", "sender_identifier")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        return value
