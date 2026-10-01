from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import IngestionCursorStatus


class IngestionCursor(Base):
    __tablename__ = "ingestion_cursors"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "account_identifier",
            name="uq_ingestion_cursors_source_account",
        ),
        CheckConstraint(
            "btrim(source) <> ''",
            name="ck_ingestion_cursors_source_not_blank",
        ),
        CheckConstraint(
            "btrim(account_identifier) <> ''",
            name="ck_ingestion_cursors_account_not_blank",
        ),
        CheckConstraint(
            "(status = 'UNINITIALIZED' AND cursor_value IS NULL) OR "
            "(status IN ('ACTIVE', 'RESYNC_REQUIRED') "
            "AND cursor_value IS NOT NULL AND btrim(cursor_value) <> '')",
            name="ck_ingestion_cursors_status_cursor",
        ),
        Index("ix_ingestion_cursors_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String)
    account_identifier: Mapped[str] = mapped_column(String)
    cursor_value: Mapped[str | None] = mapped_column(String)
    status: Mapped[IngestionCursorStatus] = mapped_column(
        Enum(
            IngestionCursorStatus,
            name="ingestion_cursor_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=IngestionCursorStatus.UNINITIALIZED,
    )
    sync_scope: Mapped[dict[str, object]] = mapped_column(JSON)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
