"""create ingestion cursors

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_cursors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("account_identifier", sa.String(), nullable=False),
        sa.Column("cursor_value", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "UNINITIALIZED",
                "ACTIVE",
                "RESYNC_REQUIRED",
                name="ingestion_cursor_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("sync_scope", sa.JSON(), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(source) <> ''",
            name="ck_ingestion_cursors_source_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(account_identifier) <> ''",
            name="ck_ingestion_cursors_account_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'UNINITIALIZED' AND cursor_value IS NULL) OR "
            "(status IN ('ACTIVE', 'RESYNC_REQUIRED') "
            "AND cursor_value IS NOT NULL AND btrim(cursor_value) <> '')",
            name="ck_ingestion_cursors_status_cursor",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "account_identifier",
            name="uq_ingestion_cursors_source_account",
        ),
    )
    op.create_index(
        "ix_ingestion_cursors_status",
        "ingestion_cursors",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_cursors_status", table_name="ingestion_cursors")
    op.drop_table("ingestion_cursors")
