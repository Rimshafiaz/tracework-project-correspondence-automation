from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RequirementState
from app.models.project import Project

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.evidence_item import EvidenceItem
    from app.models.follow_up import FollowUp
    from app.models.reply_draft import ReplyDraft


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (
        CheckConstraint(
            "btrim(name) <> ''",
            name="ck_requirements_name_not_blank",
        ),
        Index("ix_requirements_project_id", "project_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[RequirementState] = mapped_column(
        Enum(
            RequirementState,
            name="requirement_state",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=RequirementState.OPEN,
    )
    expected_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="requirements")
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="requirement"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="requirement"
    )
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="requirement")
    reply_drafts: Mapped[list["ReplyDraft"]] = relationship(back_populates="requirement")
