from sqlalchemy import Enum, JSON

from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import CorrespondenceProcessingState


def test_correspondence_event_table_contract() -> None:
    table = CorrespondenceEvent.__table__

    assert table.name == "correspondence_events"
    assert set(table.columns) == {
        table.c.id,
        table.c.source,
        table.c.external_event_id,
        table.c.external_conversation_id,
        table.c.sender_identifier,
        table.c.sender_email,
        table.c.sender_name,
        table.c.subject,
        table.c.body,
        table.c.received_at,
        table.c.processing_state,
        table.c.source_metadata,
        table.c.failure_metadata,
        table.c.created_at,
        table.c.updated_at,
    }
    assert all(
        table.c[name].nullable
        for name in (
            "external_conversation_id",
            "sender_email",
            "sender_name",
            "subject",
            "source_metadata",
            "failure_metadata",
        )
    )
    assert isinstance(table.c.processing_state.type, Enum)
    assert table.c.processing_state.type.enum_class is CorrespondenceProcessingState
    assert table.c.processing_state.default.arg is CorrespondenceProcessingState.PENDING
    assert isinstance(table.c.source_metadata.type, JSON)
    assert isinstance(table.c.failure_metadata.type, JSON)
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_correspondence_events_source_external_event",
        "ck_correspondence_events_source_not_blank",
        "ck_correspondence_events_external_event_not_blank",
        "ck_correspondence_events_sender_identifier_not_blank",
    }
    assert {index.name for index in table.indexes} >= {
        "ix_correspondence_events_source_conversation",
        "ix_correspondence_events_processing_received",
    }
