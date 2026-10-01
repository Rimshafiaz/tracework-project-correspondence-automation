from datetime import datetime
from email.utils import parseaddr

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.correspondence import NormalizedAttachment, NormalizedCorrespondenceEvent
from app.adapters.gmail.reply_boundary import select_latest_reply
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
    full_body = normalize_body(message.body)
    reply_body = select_latest_reply(full_body)
    source_metadata = None
    if reply_body.quoted_text_start is not None:
        source_metadata = {
            "full_body": full_body,
            "quoted_text_start": reply_body.quoted_text_start,
            "body_selection": "latest_reply",
        }
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
        body=reply_body.latest,
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
        source_metadata=source_metadata,
    )
