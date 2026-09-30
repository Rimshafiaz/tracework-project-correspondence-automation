from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, PrimaryKeyConstraint, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import ReviewStatus, ReviewType
from app.models.project import Project
from app.models.state_transition import StateTransition

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint(
            "state_transition_id",
            name="uq_review_items_state_transition_id",
        ),
        CheckConstraint(
            "btrim(review_reason) <> ''",
            name="ck_review_items_reason_not_blank",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND resolved_at IS NULL "
            "AND correction_payload IS NULL) OR "
            "(status = 'CORRECTED' AND resolved_at IS NOT NULL "
            "AND correction_payload IS NOT NULL) OR "
            "(status IN ('APPROVED', 'REJECTED') AND resolved_at IS NOT NULL "
            "AND correction_payload IS NULL)",
            name="ck_review_items_resolution_matches_status",
        ),
        Index("ix_review_items_status_created", "status", "created_at"),
        Index("ix_review_items_correspondence_event_id", "correspondence_event_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correspondence_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    state_transition_id: Mapped[UUID] = mapped_column(
        ForeignKey("state_transitions.id", ondelete="RESTRICT")
    )
    review_type: Mapped[ReviewType] = mapped_column(
        Enum(
            ReviewType,
            name="review_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    review_reason: Mapped[str] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            name="review_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ReviewStatus.PENDING,
    )
    correction_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    correspondence_event: Mapped[CorrespondenceEvent] = relationship(
        back_populates="review_items"
    )
    state_transition: Mapped[StateTransition] = relationship(
        back_populates="review_item"
    )
    candidate_project_links: Mapped[list["ReviewItemCandidateProject"]] = relationship(
        back_populates="review_item"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="review_item"
    )


class ReviewItemCandidateProject(Base):
    __tablename__ = "review_item_candidate_projects"
    __table_args__ = (
        PrimaryKeyConstraint(
            "review_item_id",
            "project_id",
            name="pk_review_item_candidate_projects",
        ),
        Index("ix_review_item_candidate_projects_project_id", "project_id"),
    )

    review_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_items.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )

    review_item: Mapped[ReviewItem] = relationship(
        back_populates="candidate_project_links"
    )
    project: Mapped[Project] = relationship(back_populates="review_candidate_links")
