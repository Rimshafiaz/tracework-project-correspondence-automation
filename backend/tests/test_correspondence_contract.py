from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts.correspondence import NormalizedAttachment, NormalizedCorrespondenceEvent


def test_normalized_contract_is_minimal_and_channel_neutral() -> None:
    assert set(NormalizedCorrespondenceEvent.model_fields) == {
        "source",
        "external_event_id",
        "external_conversation_id",
        "sender_identifier",
        "sender_name",
        "sender_email",
        "subject",
        "body",
        "received_at",
        "attachments",
        "source_metadata",
    }
    assert set(NormalizedAttachment.model_fields) == {
        "source_attachment_id",
        "filename",
        "mime_type",
        "size_bytes",
    }
    assert all(
        "gmail" not in field_name.casefold()
        for field_name in NormalizedCorrespondenceEvent.model_fields
    )


def test_contract_accepts_a_non_gmail_event_without_adapter_fields() -> None:
    event = NormalizedCorrespondenceEvent(
        source="fixture",
        external_event_id="event-1",
        sender_identifier="sender@example.com",
        body="Status update",
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
    )

    assert event.external_conversation_id is None
    assert event.attachments == ()
    assert event.source_metadata is None


def test_source_metadata_must_remain_json_serializable() -> None:
    with pytest.raises(ValidationError):
        NormalizedCorrespondenceEvent(
            source="fixture",
            external_event_id="event-1",
            sender_identifier="sender@example.com",
            body="Status update",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
            source_metadata={"invalid": object()},
        )
