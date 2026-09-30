from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.attachment import Attachment
from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import EvidenceValidity
from app.models.project import Project
from app.models.requirement import Requirement

if TYPE_CHECKING:
    from app.models.ai_proposal import AIProposalEvidence
    from app.models.policy_evaluation import PolicyEvaluationEvidence
    from app.models.state_transition import StateTransitionEvidence


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        CheckConstraint(
            "btrim(source_type) <> ''",
            name="ck_evidence_items_source_type_not_blank",
        ),
        CheckConstraint(
            "btrim(excerpt) <> ''",
            name="ck_evidence_items_excerpt_not_blank",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_evidence_items_page_number_positive",
        ),
        CheckConstraint(
            "(validity = 'VALID' AND invalidated_by_correspondence_event_id IS NULL "
            "AND invalidation_reason IS NULL AND invalidated_at IS NULL) OR "
            "(validity = 'INVALIDATED' "
            "AND invalidated_by_correspondence_event_id IS NOT NULL "
            "AND btrim(invalidation_reason) <> '' AND invalidated_at IS NOT NULL)",
            name="ck_evidence_items_invalidation_complete",
        ),
        Index("ix_evidence_items_correspondence_event_id", "correspondence_event_id"),
        Index("ix_evidence_items_attachment_id", "attachment_id"),
        Index("ix_evidence_items_project_id", "project_id"),
        Index(
            "ix_evidence_items_requirement_validity",
            "requirement_id",
            "validity",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correspondence_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    attachment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    requirement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    source_type: Mapped[str] = mapped_column(String)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String)
    excerpt: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(String)
    provenance_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    validity: Mapped[EvidenceValidity] = mapped_column(
        Enum(
            EvidenceValidity,
            name="evidence_validity",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=EvidenceValidity.VALID,
    )
    invalidated_by_correspondence_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    invalidation_reason: Mapped[str | None] = mapped_column(Text)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    correspondence_event: Mapped[CorrespondenceEvent] = relationship(
        back_populates="evidence_items",
        foreign_keys=[correspondence_event_id],
    )
    attachment: Mapped[Attachment | None] = relationship(back_populates="evidence_items")
    project: Mapped[Project | None] = relationship(back_populates="evidence_items")
    requirement: Mapped[Requirement | None] = relationship(
        back_populates="evidence_items"
    )
    proposal_links: Mapped[list["AIProposalEvidence"]] = relationship(
        back_populates="evidence_item"
    )
    policy_evaluation_links: Mapped[list["PolicyEvaluationEvidence"]] = relationship(
        back_populates="evidence_item"
    )
    state_transition_links: Mapped[list["StateTransitionEvidence"]] = relationship(
        back_populates="evidence_item"
    )
