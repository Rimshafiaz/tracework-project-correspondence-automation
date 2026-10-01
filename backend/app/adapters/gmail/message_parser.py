from base64 import urlsafe_b64decode
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from html.parser import HTMLParser
from typing import Any

from app.adapters.gmail.normalizer import GmailAttachment, GmailMessage


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth and data.strip():
            self.chunks.append(data.strip())


def fetch_gmail_message(service: Any, message_id: str) -> GmailMessage:
    message_id = message_id.strip()
    if not message_id:
        raise ValueError("message_id must not be blank")
    response = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    return parse_gmail_message(response)


def parse_gmail_message(response: dict[str, Any]) -> GmailMessage:
    message_id = str(response.get("id", "")).strip()
    if not message_id:
        raise ValueError("Gmail message response did not include id")

    payload = response.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Gmail message response did not include payload")

    headers = {
        str(header.get("name", "")).casefold(): str(header.get("value", ""))
        for header in payload.get("headers", ())
        if isinstance(header, dict)
    }
    sender = _decode_header(headers.get("from", "")).strip()
    if not sender:
        raise ValueError("Gmail message payload did not include From header")

    try:
        received_at = datetime.fromtimestamp(
            int(response["internalDate"]) / 1000,
            tz=UTC,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("Gmail message response has invalid internalDate") from error

    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[GmailAttachment] = []
    _collect_parts(payload, plain_parts, html_parts, attachments)
    body = "\n\n".join(plain_parts)
    if not body and html_parts:
        extractor = _TextExtractor()
        extractor.feed("\n".join(html_parts))
        body = "\n".join(extractor.chunks)

    subject = _decode_header(headers.get("subject", "")).strip() or None
    thread_id = str(response.get("threadId", "")).strip() or None
    return GmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender_header=sender,
        subject=subject,
        body=body,
        received_at=received_at,
        attachments=tuple(attachments),
    )


def _collect_parts(
    part: dict[str, Any],
    plain_parts: list[str],
    html_parts: list[str],
    attachments: list[GmailAttachment],
) -> None:
    filename = str(part.get("filename", "")).strip()
    mime_type = str(part.get("mimeType", "application/octet-stream"))
    body = part.get("body") if isinstance(part.get("body"), dict) else {}

    if filename:
        api_id = str(body.get("attachmentId", "")).strip()
        part_id = str(part.get("partId", "")).strip()
        if api_id:
            attachment_id = f"api:{api_id}"
        elif part_id:
            attachment_id = f"part:{part_id}"
        else:
            raise ValueError(f"Gmail attachment {filename!r} has no source identifier")
        attachments.append(
            GmailAttachment(
                attachment_id=attachment_id,
                filename=filename,
                mime_type=mime_type,
                size_bytes=int(body.get("size", 0)),
            )
        )
    elif mime_type in {"text/plain", "text/html"} and body.get("data"):
        decoded = _decode_part(str(body["data"]), part)
        (plain_parts if mime_type == "text/plain" else html_parts).append(decoded)

    for child in part.get("parts", ()):
        if isinstance(child, dict):
            _collect_parts(child, plain_parts, html_parts, attachments)


def _decode_part(data: str, part: dict[str, Any]) -> str:
    padding = "=" * (-len(data) % 4)
    decoded = urlsafe_b64decode(data + padding)
    content_type = next(
        (
            str(header.get("value", ""))
            for header in part.get("headers", ())
            if isinstance(header, dict)
            and str(header.get("name", "")).casefold() == "content-type"
        ),
        "",
    )
    message = Message()
    if content_type:
        message["content-type"] = content_type
    charset = message.get_content_charset() or "utf-8"
    try:
        return decoded.decode(charset, errors="replace").strip()
    except LookupError:
        return decoded.decode("utf-8", errors="replace").strip()


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return value
