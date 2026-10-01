from base64 import urlsafe_b64encode
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.adapters.gmail.attachment_content import (
    AttachmentContentError,
    AttachmentContentFailure,
    download_gmail_attachment,
)
from app.contracts.attachment_content import AttachmentContent


def encoded(content: bytes) -> str:
    return urlsafe_b64encode(content).decode().rstrip("=")


def test_attachment_content_rejects_incorrect_size() -> None:
    with pytest.raises(ValidationError, match="decoded content length"):
        AttachmentContent(
            attachment_id=uuid4(),
            content=b"abc",
            size_bytes=4,
        )


def test_downloads_api_attachment_and_returns_channel_neutral_content() -> None:
    service = MagicMock()
    get = service.users.return_value.messages.return_value.attachments.return_value.get
    get.return_value.execute.return_value = {
        "data": encoded(b"PDF bytes"),
        "size": 9,
    }
    attachment_id = uuid4()

    result = download_gmail_attachment(
        service,
        attachment_id=attachment_id,
        message_id="message-1",
        source_attachment_id="api:attachment-1",
        declared_size_bytes=9,
        max_size_bytes=100,
    )

    assert result.attachment_id == attachment_id
    assert result.content == b"PDF bytes"
    assert result.size_bytes == 9
    get.assert_called_once_with(
        userId="me",
        messageId="message-1",
        id="attachment-1",
    )


def test_downloads_inline_attachment_from_nested_mime_part() -> None:
    service = MagicMock()
    get = service.users.return_value.messages.return_value.get
    get.return_value.execute.return_value = {
        "payload": {
            "parts": [
                {
                    "partId": "container",
                    "parts": [
                        {
                            "partId": "2",
                            "body": {"data": encoded(b"DOCX bytes"), "size": 10},
                        }
                    ],
                }
            ]
        }
    }

    result = download_gmail_attachment(
        service,
        attachment_id=uuid4(),
        message_id="message-1",
        source_attachment_id="part:2",
        declared_size_bytes=10,
        max_size_bytes=100,
    )

    assert result.content == b"DOCX bytes"
    get.assert_called_once_with(userId="me", id="message-1", format="full")


def test_rejects_declared_oversize_before_calling_gmail() -> None:
    service = MagicMock()

    with pytest.raises(AttachmentContentError) as raised:
        download_gmail_attachment(
            service,
            attachment_id=uuid4(),
            message_id="message-1",
            source_attachment_id="api:attachment-1",
            declared_size_bytes=101,
            max_size_bytes=100,
        )

    assert raised.value.reason is AttachmentContentFailure.ATTACHMENT_TOO_LARGE
    service.users.assert_not_called()


@pytest.mark.parametrize(
    ("source_attachment_id", "response", "reason"),
    [
        (
            "api:attachment-1",
            {"data": "not valid base64!", "size": 3},
            AttachmentContentFailure.INVALID_BASE64_DATA,
        ),
        (
            "api:attachment-1",
            {"size": 3},
            AttachmentContentFailure.ATTACHMENT_DATA_MISSING,
        ),
        (
            "api:attachment-1",
            {"data": encoded(b"abc"), "size": 4},
            AttachmentContentFailure.CONTENT_SIZE_MISMATCH,
        ),
    ],
)
def test_rejects_invalid_api_attachment_data(
    source_attachment_id: str,
    response: dict,
    reason: AttachmentContentFailure,
) -> None:
    service = MagicMock()
    service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = response

    with pytest.raises(AttachmentContentError) as raised:
        download_gmail_attachment(
            service,
            attachment_id=uuid4(),
            message_id="message-1",
            source_attachment_id=source_attachment_id,
            declared_size_bytes=3,
            max_size_bytes=100,
        )

    assert raised.value.reason is reason


def test_rejects_missing_inline_part() -> None:
    service = MagicMock()
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {"parts": []}
    }

    with pytest.raises(AttachmentContentError) as raised:
        download_gmail_attachment(
            service,
            attachment_id=uuid4(),
            message_id="message-1",
            source_attachment_id="part:missing",
            declared_size_bytes=3,
            max_size_bytes=100,
        )

    assert raised.value.reason is AttachmentContentFailure.ATTACHMENT_NOT_FOUND
