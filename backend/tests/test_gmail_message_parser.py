from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.adapters.gmail.message_parser import fetch_gmail_message, parse_gmail_message


def encoded(value: str, encoding: str = "utf-8") -> str:
    return urlsafe_b64encode(value.encode(encoding)).decode().rstrip("=")


def message(payload: dict) -> dict:
    return {
        "id": "message-1",
        "threadId": "thread-1",
        "internalDate": "1790838000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "Subject", "value": "Status update"},
            ],
            **payload,
        },
    }


def test_fetches_full_message_and_parses_plain_text() -> None:
    service = MagicMock()
    response = message(
        {"mimeType": "text/plain", "body": {"data": encoded("Hello")}}
    )
    get = service.users.return_value.messages.return_value.get
    get.return_value.execute.return_value = response

    result = fetch_gmail_message(service, " message-1 ")

    get.assert_called_once_with(userId="me", id="message-1", format="full")
    assert result.message_id == "message-1"
    assert result.thread_id == "thread-1"
    assert result.sender_header == "Sender <sender@example.com>"
    assert result.subject == "Status update"
    assert result.body == "Hello"
    assert result.received_at == datetime.fromtimestamp(1790838000, tz=UTC)


def test_prefers_plain_text_and_collects_nested_attachment_metadata() -> None:
    result = parse_gmail_message(
        message(
            {
                "mimeType": "multipart/mixed",
                "body": {},
                "parts": [
                    {
                        "partId": "0",
                        "mimeType": "multipart/alternative",
                        "body": {},
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": encoded("Plain")}},
                            {"mimeType": "text/html", "body": {"data": encoded("<b>HTML</b>")}},
                        ],
                    },
                    {
                        "partId": "1",
                        "mimeType": "application/pdf",
                        "filename": "report.pdf",
                        "body": {"attachmentId": "attachment-1", "size": 321},
                    },
                ],
            }
        )
    )

    assert result.body == "Plain"
    assert result.attachments[0].model_dump() == {
        "attachment_id": "api:attachment-1",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 321,
    }


def test_collects_inline_attachment_with_part_locator() -> None:
    result = parse_gmail_message(
        message(
            {
                "mimeType": "multipart/mixed",
                "body": {},
                "parts": [
                    {
                        "partId": "2",
                        "mimeType": "application/pdf",
                        "filename": "inline.pdf",
                        "body": {"data": encoded("PDF bytes"), "size": 9},
                    }
                ],
            }
        )
    )

    assert result.attachments[0].attachment_id == "part:2"


def test_uses_readable_html_fallback_without_script_or_style_content() -> None:
    result = parse_gmail_message(
        message(
            {
                "mimeType": "text/html",
                "body": {
                    "data": encoded(
                        "<style>hidden</style><p>Hello <b>team</b></p><script>bad()</script>"
                    )
                },
            }
        )
    )

    assert result.body == "Hello\nteam"


def test_decodes_declared_charset_and_encoded_headers() -> None:
    response = message(
        {
            "mimeType": "text/plain",
            "body": {"data": encoded("café", "iso-8859-1")},
        }
    )
    response["payload"]["headers"][1]["value"] = "=?utf-8?q?Caf=C3=A9?="
    response["payload"]["headers"].append(
        {"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}
    )

    result = parse_gmail_message(response)

    assert result.subject == "Café"
    assert result.body == "café"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda value: value["payload"].update(headers=[]), "From header"),
        (lambda value: value.update(internalDate="not-a-number"), "internalDate"),
    ],
)
def test_rejects_missing_or_malformed_required_metadata(change, error: str) -> None:
    response = message({"mimeType": "text/plain", "body": {}})
    change(response)

    with pytest.raises(ValueError, match=error):
        parse_gmail_message(response)
