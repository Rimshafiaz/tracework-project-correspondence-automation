"""create documents

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_attachment_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column(
            "filing_status",
            sa.Enum(
                "PENDING",
                "RETRYABLE_FAILURE",
                "FILED",
                name="document_filing_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("drive_file_id", sa.String(), nullable=True),
        sa.Column("drive_parent_folder_id", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
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
            "btrim(filename) <> ''", name="ck_documents_filename_not_blank"
        ),
        sa.CheckConstraint(
            "btrim(category) <> ''", name="ck_documents_category_not_blank"
        ),
        sa.CheckConstraint(
            "btrim(content_hash) <> ''", name="ck_documents_hash_not_blank"
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_documents_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "(filing_status = 'FILED' AND drive_file_id IS NOT NULL "
            "AND drive_parent_folder_id IS NOT NULL AND filed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(filing_status <> 'FILED' AND drive_file_id IS NULL "
            "AND filed_at IS NULL)",
            name="ck_documents_filing_state_complete",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_attachment_id"], ["attachments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "source_attachment_id",
            name="uq_documents_project_source_attachment",
        ),
        sa.UniqueConstraint("drive_file_id", name="uq_documents_drive_file_id"),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_index(
        "ix_documents_source_attachment_id",
        "documents",
        ["source_attachment_id"],
    )
    op.create_index(
        "ix_documents_filing_status",
        "documents",
        ["filing_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_filing_status", table_name="documents")
    op.drop_index("ix_documents_source_attachment_id", table_name="documents")
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
