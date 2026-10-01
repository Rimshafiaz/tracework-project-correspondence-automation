from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.adapters.gmail.normalizer import GmailAttachment, GmailMessage, normalize_gmail_message
from app.contracts.correspondence import NormalizedCorrespondenceEvent
from app.normalization.correspondence import normalize_body, normalize_email, normalize_source


def test_source_independent_normalizers_are_deterministic() -> None:
    assert normalize_source("  Email Provider ") == "email provider"
    assert normalize_email(" Person@Example.COM ") == "person@example.com"
    assert normalize_body("first\r\nsecond\rthird") == "first\nsecond\nthird"


def test_normalized_event_rejects_blank_identity_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        NormalizedCorrespondenceEvent(
            source=" ",
            external_event_id="event-1",
            sender_identifier="sender@example.com",
            body="Update",
            received_at=datetime(2026, 10, 1),
        )


def test_gmail_mapper_produces_channel_neutral_contract() -> None:
    message = GmailMessage(
        message_id=" message-1 ",
        thread_id=" thread-1 ",
        sender_header="Example Person <Person@Example.COM>",
        subject="Status update",
        body="First line\r\nSecond line",
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
        attachments=(
            GmailAttachment(
                attachment_id="attachment-1",
                filename="status.pdf",
                mime_type="application/pdf",
                size_bytes=100,
            ),
        ),
    )

    event = normalize_gmail_message(message)

    assert type(event) is NormalizedCorrespondenceEvent
    assert event.source == "gmail"
    assert event.external_event_id == "message-1"
    assert event.external_conversation_id == "thread-1"
    assert event.sender_identifier == "person@example.com"
    assert event.sender_name == "Example Person"
    assert event.body == "First line\nSecond line"
    assert event.attachments[0].source_attachment_id == "attachment-1"
    assert not hasattr(event, "gmail_message_id")


def test_gmail_mapper_preserves_full_body_when_selecting_latest_reply() -> None:
    body = "Latest answer.\n\nOn Tue, Sep 30, 2026 Sender wrote:\nEarlier message"
    message = GmailMessage(
        message_id="message-2",
        sender_header="sender@example.com",
        body=body,
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
    )

    event = normalize_gmail_message(message)

    assert event.body == "Latest answer."
    assert event.source_metadata == {
        "full_body": body,
        "quoted_text_start": body.index("On Tue"),
        "body_selection": "latest_reply",
    }
