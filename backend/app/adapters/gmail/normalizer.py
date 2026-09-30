from datetime import datetime
from email.utils import parseaddr

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.correspondence import NormalizedAttachment, NormalizedCorrespondenceEvent
from app.normalization.correspondence import normalize_body, normalize_email


class GmailAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)


class GmailMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    thread_id: str | None = None
    sender_header: str
    subject: str | None = None
    body: str
    received_at: datetime
    attachments: tuple[GmailAttachment, ...] = ()


def normalize_gmail_message(message: GmailMessage) -> NormalizedCorrespondenceEvent:
    sender_name, sender_email = parseaddr(message.sender_header)
    normalized_sender_email = normalize_email(sender_email)
    sender_identifier = normalized_sender_email or message.sender_header.strip()
    return NormalizedCorrespondenceEvent(
        source="gmail",
        external_event_id=message.message_id.strip(),
        external_conversation_id=(
            message.thread_id.strip() if message.thread_id else None
        ),
        sender_identifier=sender_identifier,
        sender_name=sender_name.strip() or None,
        sender_email=normalized_sender_email or None,
        subject=message.subject,
        body=normalize_body(message.body),
        received_at=message.received_at,
        attachments=tuple(
            NormalizedAttachment(
                source_attachment_id=attachment.attachment_id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                size_bytes=attachment.size_bytes,
            )
            for attachment in message.attachments
        ),
    )
