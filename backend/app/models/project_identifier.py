from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.project import Project


class ProjectIdentifier(Base):
    __tablename__ = "project_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "identifier_type",
            "normalized_value",
            name="uq_project_identifiers_project_type_value",
        ),
        CheckConstraint(
            "btrim(identifier_type) <> ''",
            name="ck_project_identifiers_type_not_blank",
        ),
        CheckConstraint(
            "btrim(display_value) <> ''",
            name="ck_project_identifiers_display_value_not_blank",
        ),
        CheckConstraint(
            "btrim(normalized_value) <> ''",
            name="ck_project_identifiers_normalized_value_not_blank",
        ),
        Index(
            "ix_project_identifiers_type_normalized_value",
            "identifier_type",
            "normalized_value",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    identifier_type: Mapped[str] = mapped_column(String)
    display_value: Mapped[str] = mapped_column(String)
    normalized_value: Mapped[str] = mapped_column(String)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="identifiers")

