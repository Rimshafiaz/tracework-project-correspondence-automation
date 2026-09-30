from sqlalchemy import BigInteger, Enum, JSON

from app.models.attachment import Attachment
from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import AttachmentProcessingState


def test_attachment_table_contract() -> None:
    table = Attachment.__table__

    assert table.name == "attachments"
    assert set(table.columns) == {
        table.c.id,
        table.c.correspondence_event_id,
        table.c.source_attachment_id,
        table.c.filename,
        table.c.mime_type,
        table.c.size_bytes,
        table.c.content_hash,
        table.c.extracted_text,
        table.c.extraction_metadata,
        table.c.parsed_metadata,
        table.c.processing_state,
        table.c.created_at,
        table.c.updated_at,
    }
    assert isinstance(table.c.size_bytes.type, BigInteger)
    assert isinstance(table.c.extraction_metadata.type, JSON)
    assert isinstance(table.c.parsed_metadata.type, JSON)
    assert isinstance(table.c.processing_state.type, Enum)
    assert table.c.processing_state.type.enum_class is AttachmentProcessingState
    assert table.c.processing_state.default.arg is AttachmentProcessingState.PENDING
    assert all(
        table.c[name].nullable
        for name in (
            "content_hash",
            "extracted_text",
            "extraction_metadata",
            "parsed_metadata",
        )
    )
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_attachments_event_source_attachment",
        "ck_attachments_source_id_not_blank",
        "ck_attachments_filename_not_blank",
        "ck_attachments_mime_type_not_blank",
        "ck_attachments_size_nonnegative",
    }
    foreign_key = next(iter(table.c.correspondence_event_id.foreign_keys))
    assert foreign_key.target_fullname == "correspondence_events.id"
    assert foreign_key.ondelete == "RESTRICT"
    assert {index.name for index in table.indexes} >= {
        "ix_attachments_correspondence_event_id",
        "ix_attachments_processing_state",
    }
    assert CorrespondenceEvent.attachments.property.back_populates == (
        "correspondence_event"
    )
