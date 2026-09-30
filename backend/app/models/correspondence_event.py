from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, JSON, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import CorrespondenceProcessingState

if TYPE_CHECKING:
    from app.models.ai_proposal import AIProposal
    from app.models.audit_event import AuditEvent
    from app.models.attachment import Attachment
    from app.models.correspondence_project_link import CorrespondenceProjectLink
    from app.models.evidence_item import EvidenceItem
    from app.models.review_item import ReviewItem


class CorrespondenceEvent(Base):
    __tablename__ = "correspondence_events"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_event_id",
            name="uq_correspondence_events_source_external_event",
        ),
        CheckConstraint(
            "btrim(source) <> ''",
            name="ck_correspondence_events_source_not_blank",
        ),
        CheckConstraint(
            "btrim(external_event_id) <> ''",
            name="ck_correspondence_events_external_event_not_blank",
        ),
        CheckConstraint(
            "btrim(sender_identifier) <> ''",
            name="ck_correspondence_events_sender_identifier_not_blank",
        ),
        Index(
            "ix_correspondence_events_source_conversation",
            "source",
            "external_conversation_id",
        ),
        Index(
            "ix_correspondence_events_processing_received",
            "processing_state",
            "received_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String)
    external_event_id: Mapped[str] = mapped_column(String)
    external_conversation_id: Mapped[str | None] = mapped_column(String)
    sender_identifier: Mapped[str] = mapped_column(String)
    sender_email: Mapped[str | None] = mapped_column(String)
    sender_name: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_state: Mapped[CorrespondenceProcessingState] = mapped_column(
        Enum(
            CorrespondenceProcessingState,
            name="correspondence_processing_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=CorrespondenceProcessingState.PENDING,
    )
    source_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    failure_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    project_links: Mapped[list["CorrespondenceProjectLink"]] = relationship(
        back_populates="correspondence_event"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="correspondence_event"
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="correspondence_event",
        foreign_keys="EvidenceItem.correspondence_event_id",
    )
    ai_proposals: Mapped[list["AIProposal"]] = relationship(
        back_populates="correspondence_event"
    )
    review_items: Mapped[list["ReviewItem"]] = relationship(
        back_populates="correspondence_event"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="correspondence_event"
    )
