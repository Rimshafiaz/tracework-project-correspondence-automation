from base64 import b64decode
from binascii import Error as Base64Error
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.contracts.attachment_content import AttachmentContent


class AttachmentContentFailure(StrEnum):
    ATTACHMENT_TOO_LARGE = "ATTACHMENT_TOO_LARGE"
    ATTACHMENT_NOT_FOUND = "ATTACHMENT_NOT_FOUND"
    ATTACHMENT_DATA_MISSING = "ATTACHMENT_DATA_MISSING"
    INVALID_BASE64_DATA = "INVALID_BASE64_DATA"
    CONTENT_SIZE_MISMATCH = "CONTENT_SIZE_MISMATCH"


class AttachmentContentError(Exception):
    def __init__(self, reason: AttachmentContentFailure) -> None:
        self.reason = reason
        super().__init__(reason.value)


def download_gmail_attachment(
    service: Any,
    *,
    attachment_id: UUID,
    message_id: str,
    source_attachment_id: str,
    declared_size_bytes: int,
    max_size_bytes: int,
) -> AttachmentContent:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")
    if declared_size_bytes > max_size_bytes:
        raise AttachmentContentError(
            AttachmentContentFailure.ATTACHMENT_TOO_LARGE
        )

    locator_type, separator, locator_value = source_attachment_id.partition(":")
    if not separator or not locator_value:
        raise AttachmentContentError(AttachmentContentFailure.ATTACHMENT_NOT_FOUND)

    if locator_type == "api":
        body = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=locator_value)
            .execute()
        )
    elif locator_type == "part":
        response = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        part = _find_part(response.get("payload"), locator_value)
        if part is None:
            raise AttachmentContentError(
                AttachmentContentFailure.ATTACHMENT_NOT_FOUND
            )
        body = part.get("body") if isinstance(part.get("body"), dict) else {}
    else:
        raise AttachmentContentError(AttachmentContentFailure.ATTACHMENT_NOT_FOUND)

    if "data" not in body:
        raise AttachmentContentError(
            AttachmentContentFailure.ATTACHMENT_DATA_MISSING
        )
    content = _decode_base64url(str(body["data"]))
    if len(content) > max_size_bytes:
        raise AttachmentContentError(
            AttachmentContentFailure.ATTACHMENT_TOO_LARGE
        )

    provider_size = body.get("size")
    try:
        provider_size_mismatch = (
            provider_size is not None and int(provider_size) != len(content)
        )
    except (TypeError, ValueError):
        provider_size_mismatch = True
    if provider_size_mismatch or declared_size_bytes != len(content):
        raise AttachmentContentError(
            AttachmentContentFailure.CONTENT_SIZE_MISMATCH
        )
    return AttachmentContent(
        attachment_id=attachment_id,
        content=content,
        size_bytes=len(content),
    )


def _decode_base64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return b64decode(
            (data + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (Base64Error, UnicodeEncodeError, ValueError) as error:
        raise AttachmentContentError(
            AttachmentContentFailure.INVALID_BASE64_DATA
        ) from error


def _find_part(part: object, part_id: str) -> dict[str, Any] | None:
    if not isinstance(part, dict):
        return None
    if str(part.get("partId", "")) == part_id:
        return part
    for child in part.get("parts", ()):
        found = _find_part(child, part_id)
        if found is not None:
            return found
    return None
