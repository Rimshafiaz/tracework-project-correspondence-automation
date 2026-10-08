from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from re import findall
from typing import Any
from uuid import UUID


GMAIL_REPLY_METADATA_HEADERS = (
    "Message-ID",
    "References",
    "In-Reply-To",
    "Subject",
    "From",
)


@dataclass(frozen=True)
class GmailLiveSourceMetadata:
    message_id: str
    thread_id: str
    rfc_message_id: str
    references: str | None
    in_reply_to: str | None
    subject: str | None
    sender: str


@dataclass(frozen=True)
class GmailReplyMessage:
    raw: str
    thread_id: str
    rfc_message_id: str
    subject: str


@dataclass(frozen=True)
class GmailSendReceipt:
    message_id: str
    thread_id: str


@dataclass(frozen=True)
class GmailRecoverySearch:
    message_ids: tuple[str, ...]
    thread_ids: tuple[str | None, ...]


class GmailReplyMetadataError(ValueError):
    pass


def fetch_live_source_metadata(service: Any, message_id: str) -> GmailLiveSourceMetadata:
    message_id = _required(message_id, "message_id")
    response = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=list(GMAIL_REPLY_METADATA_HEADERS),
        )
        .execute()
    )
    return parse_live_source_metadata(response)


def parse_live_source_metadata(response: dict[str, Any]) -> GmailLiveSourceMetadata:
    message_id = _required(response.get("id"), "Gmail response id")
    thread_id = _required(response.get("threadId"), "Gmail response threadId")
    payload = response.get("payload")
    if not isinstance(payload, dict):
        raise GmailReplyMetadataError("Gmail response did not include payload")
    headers = {
        str(item.get("name", "")).casefold(): str(item.get("value", "")).strip()
        for item in payload.get("headers", ())
        if isinstance(item, dict)
    }
    return GmailLiveSourceMetadata(
        message_id=message_id,
        thread_id=thread_id,
        rfc_message_id=_required(headers.get("message-id"), "Message-ID header"),
        references=headers.get("references") or None,
        in_reply_to=headers.get("in-reply-to") or None,
        subject=headers.get("subject") or None,
        sender=_required(headers.get("from"), "From header"),
    )


def deterministic_rfc_message_id(send_attempt_id: UUID, domain: str) -> str:
    domain = _required(domain, "message-id domain").lower()
    return f"<tracework-reply-{send_attempt_id}@{domain}>"


def build_gmail_reply(
    *,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    thread_id: str,
    source: GmailLiveSourceMetadata,
    rfc_message_id: str,
) -> GmailReplyMessage:
    sender_email = _required(sender_email, "sender_email")
    recipient_email = _required(recipient_email, "recipient_email")
    subject = normalize_reply_subject(_required(subject, "subject"))
    body = _required(body, "body")
    thread_id = _required(thread_id, "thread_id")
    if source.thread_id != thread_id:
        raise GmailReplyMetadataError("live Gmail thread does not match persisted thread")
    rfc_message_id = _required(rfc_message_id, "rfc_message_id")
    message = EmailMessage(policy=SMTP)
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject
    message["Message-ID"] = rfc_message_id
    message["In-Reply-To"] = source.rfc_message_id
    message["References"] = " ".join(_references(source.references, source.rfc_message_id))
    message.set_content(body)
    return GmailReplyMessage(
        raw=urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("="),
        thread_id=thread_id,
        rfc_message_id=rfc_message_id,
        subject=subject,
    )


def search_sent_by_rfc_message_id(
    service: Any,
    *,
    rfc_message_id: str,
    max_results: int = 3,
) -> GmailRecoverySearch:
    if max_results < 1 or max_results > 10:
        raise ValueError("max_results must be between 1 and 10")
    query_id = _required(rfc_message_id, "rfc_message_id").strip("<>")
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=f"in:sent rfc822msgid:{query_id}",
            maxResults=max_results,
        )
        .execute()
    )
    messages = response.get("messages", ())
    if not isinstance(messages, list):
        raise GmailReplyMetadataError("Gmail recovery response has invalid messages")
    ids: list[str] = []
    threads: list[str | None] = []
    for item in messages:
        if not isinstance(item, dict):
            raise GmailReplyMetadataError("Gmail recovery response has invalid message")
        ids.append(_required(item.get("id"), "Gmail recovery message id"))
        thread = str(item.get("threadId") or "").strip() or None
        threads.append(thread)
    return GmailRecoverySearch(message_ids=tuple(ids), thread_ids=tuple(threads))


def send_gmail_reply(service: Any, reply: GmailReplyMessage) -> GmailSendReceipt:
    response = (
        service.users()
        .messages()
        .send(
            userId="me",
            body={"raw": reply.raw},
            threadId=reply.thread_id,
        )
        .execute()
    )
    receipt = GmailSendReceipt(
        message_id=_required(response.get("id"), "Gmail send response id"),
        thread_id=_required(response.get("threadId"), "Gmail send response threadId"),
    )
    if receipt.thread_id != reply.thread_id:
        raise GmailReplyMetadataError("Gmail send response thread does not match reply")
    return receipt


def _references(existing: str | None, source_rfc_message_id: str) -> tuple[str, ...]:
    values = list(findall(r"<[^<>]+>", existing or ""))
    if source_rfc_message_id not in values:
        values.append(source_rfc_message_id)
    return tuple(dict.fromkeys(values))


def normalize_reply_subject(subject: str) -> str:
    normalized = subject.strip()
    while normalized.casefold().startswith("re:"):
        normalized = normalized[3:].lstrip()
    return f"Re: {normalized}"


def _required(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise GmailReplyMetadataError(f"{label} must not be blank")
    return normalized
