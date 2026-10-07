from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DocumentFilingStatus

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.project import Project


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_attachment_id",
            name="uq_documents_project_source_attachment",
        ),
        UniqueConstraint("drive_file_id", name="uq_documents_drive_file_id"),
        CheckConstraint("btrim(filename) <> ''", name="ck_documents_filename_not_blank"),
        CheckConstraint("btrim(category) <> ''", name="ck_documents_category_not_blank"),
        CheckConstraint("btrim(content_hash) <> ''", name="ck_documents_hash_not_blank"),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_documents_hash_sha256_length",
        ),
        CheckConstraint(
            "(filing_status = 'FILED' AND drive_file_id IS NOT NULL "
            "AND drive_parent_folder_id IS NOT NULL AND filed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(filing_status <> 'FILED' AND drive_file_id IS NULL "
            "AND filed_at IS NULL)",
            name="ck_documents_filing_state_complete",
        ),
        Index("ix_documents_project_id", "project_id"),
        Index("ix_documents_source_attachment_id", "source_attachment_id"),
        Index("ix_documents_filing_status", "filing_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    source_attachment_id: Mapped[UUID] = mapped_column(
        ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    filename: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    filing_status: Mapped[DocumentFilingStatus] = mapped_column(
        Enum(
            DocumentFilingStatus,
            name="document_filing_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=DocumentFilingStatus.PENDING,
    )
    drive_file_id: Mapped[str | None] = mapped_column(String)
    drive_parent_folder_id: Mapped[str | None] = mapped_column(String)
    failure_code: Mapped[str | None] = mapped_column(String)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="documents")
    source_attachment: Mapped["Attachment"] = relationship(back_populates="documents")
