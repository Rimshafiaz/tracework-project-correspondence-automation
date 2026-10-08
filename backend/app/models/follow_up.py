from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import FollowUpCancelReason, FollowUpPurpose, FollowUpStatus

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.project import Project
    from app.models.requirement import Requirement
    from app.models.state_transition import StateTransition
    from app.models.reply_draft import ReplyDraft


class FollowUp(Base):
    __tablename__ = "follow_ups"
    __table_args__ = (
        CheckConstraint("btrim(reason) <> ''", name="ck_follow_ups_reason_not_blank"),
        CheckConstraint(
            "(originating_state_transition_id IS NOT NULL AND "
            "originating_audit_event_id IS NULL) OR "
            "(originating_state_transition_id IS NULL AND "
            "originating_audit_event_id IS NOT NULL)",
            name="ck_follow_ups_exactly_one_origin",
        ),
        CheckConstraint(
            "due_on = expected_date + 1",
            name="ck_follow_ups_due_after_expected_date",
        ),
        CheckConstraint(
            "(status = 'SCHEDULED' AND became_due_at IS NULL "
            "AND cancelled_at IS NULL AND cancel_reason IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'DUE' AND became_due_at IS NOT NULL "
            "AND cancelled_at IS NULL AND cancel_reason IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'COMPLETED' AND became_due_at IS NOT NULL "
            "AND cancelled_at IS NULL AND cancel_reason IS NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_follow_ups_status_timestamps",
        ),
        CheckConstraint(
            "(cancel_reason = 'EXPECTED_DATE_CHANGED' "
            "AND superseded_by_follow_up_id IS NOT NULL) OR "
            "(cancel_reason IS DISTINCT FROM 'EXPECTED_DATE_CHANGED' "
            "AND superseded_by_follow_up_id IS NULL)",
            name="ck_follow_ups_supersession_matches_reason",
        ),
        CheckConstraint(
            "superseded_by_follow_up_id IS NULL OR superseded_by_follow_up_id <> id",
            name="ck_follow_ups_not_self_superseded",
        ),
        Index("ix_follow_ups_project_created", "project_id", "created_at"),
        Index("ix_follow_ups_requirement_created", "requirement_id", "created_at"),
        Index("ix_follow_ups_status_due", "status", "due_on", "id"),
        Index(
            "uq_follow_ups_transition_origin",
            "originating_state_transition_id",
            "requirement_id",
            "purpose",
            unique=True,
            postgresql_where=text("originating_state_transition_id IS NOT NULL"),
        ),
        Index(
            "uq_follow_ups_audit_origin",
            "originating_audit_event_id",
            "requirement_id",
            "purpose",
            unique=True,
            postgresql_where=text("originating_audit_event_id IS NOT NULL"),
        ),
        Index(
            "uq_follow_ups_active_requirement_purpose",
            "requirement_id",
            "purpose",
            unique=True,
            postgresql_where=text("status IN ('SCHEDULED', 'DUE')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    requirement_id: Mapped[UUID] = mapped_column(ForeignKey("requirements.id", ondelete="RESTRICT"))
    originating_state_transition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("state_transitions.id", ondelete="RESTRICT")
    )
    originating_audit_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("audit_events.id", ondelete="RESTRICT")
    )
    purpose: Mapped[FollowUpPurpose] = mapped_column(
        Enum(FollowUpPurpose, name="follow_up_purpose", native_enum=False, create_constraint=True, validate_strings=True)
    )
    reason: Mapped[str] = mapped_column(Text)
    expected_date: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus, name="follow_up_status", native_enum=False, create_constraint=True, validate_strings=True),
        default=FollowUpStatus.SCHEDULED,
    )
    superseded_by_follow_up_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "follow_ups.id",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        )
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[FollowUpCancelReason | None] = mapped_column(
        Enum(FollowUpCancelReason, name="follow_up_cancel_reason", native_enum=False, create_constraint=True, validate_strings=True)
    )
    became_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="follow_ups")
    requirement: Mapped["Requirement"] = relationship(back_populates="follow_ups")
    originating_state_transition: Mapped["StateTransition | None"] = relationship(back_populates="originated_follow_ups")
    originating_audit_event: Mapped["AuditEvent | None"] = relationship(back_populates="originated_follow_ups")
    superseded_by: Mapped["FollowUp | None"] = relationship(
        remote_side="FollowUp.id",
        foreign_keys=[superseded_by_follow_up_id],
    )
    reply_drafts: Mapped[list["ReplyDraft"]] = relationship(back_populates="follow_up")
