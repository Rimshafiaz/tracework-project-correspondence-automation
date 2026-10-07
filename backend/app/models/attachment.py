from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import AttachmentProcessingState

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.evidence_item import EvidenceItem


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "correspondence_event_id",
            "source_attachment_id",
            name="uq_attachments_event_source_attachment",
        ),
        CheckConstraint(
            "btrim(source_attachment_id) <> ''",
            name="ck_attachments_source_id_not_blank",
        ),
        CheckConstraint(
            "btrim(filename) <> ''",
            name="ck_attachments_filename_not_blank",
        ),
        CheckConstraint(
            "btrim(mime_type) <> ''",
            name="ck_attachments_mime_type_not_blank",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_attachments_size_nonnegative"),
        Index("ix_attachments_correspondence_event_id", "correspondence_event_id"),
        Index("ix_attachments_processing_state", "processing_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correspondence_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    source_attachment_id: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(String)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    parsed_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    processing_state: Mapped[AttachmentProcessingState] = mapped_column(
        Enum(
            AttachmentProcessingState,
            name="attachment_processing_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=AttachmentProcessingState.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    correspondence_event: Mapped[CorrespondenceEvent] = relationship(
        back_populates="attachments"
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="attachment"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="source_attachment"
    )
