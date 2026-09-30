from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.project import Project


class ProjectContact(Base):
    __tablename__ = "project_contacts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "email_normalized",
            name="uq_project_contacts_project_email",
        ),
        CheckConstraint(
            "btrim(email_normalized) <> ''",
            name="ck_project_contacts_email_not_blank",
        ),
        CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_project_contacts_name_not_blank",
        ),
        Index("ix_project_contacts_email_normalized", "email_normalized"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    email_normalized: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="contacts")
