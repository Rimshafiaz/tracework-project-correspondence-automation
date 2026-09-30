from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.correspondence_event import CorrespondenceEvent
from app.models.project import Project


class CorrespondenceProjectLink(Base):
    __tablename__ = "correspondence_project_links"
    __table_args__ = (
        UniqueConstraint(
            "correspondence_event_id",
            "project_id",
            name="uq_correspondence_project_links_event_project",
        ),
        Index("ix_correspondence_project_links_project_id", "project_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correspondence_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    correspondence_event: Mapped[CorrespondenceEvent] = relationship(
        back_populates="project_links"
    )
    project: Mapped[Project] = relationship(back_populates="correspondence_links")

