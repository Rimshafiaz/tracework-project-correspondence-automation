"""add document revision persistence

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("document_family_key", sa.String(), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("revision_label", sa.String(), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("revision_normalized", sa.String(), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("revision_order", sa.Integer(), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column(
            "revision_status",
            sa.Enum(
                "UNASSESSED",
                "CURRENT",
                "HISTORICAL",
                "DUPLICATE",
                "REVIEW_REQUIRED",
                name="document_revision_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="UNASSESSED",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("revision_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_revision_pair_complete",
        "documents",
        "(revision_normalized IS NULL AND revision_order IS NULL) OR "
        "(revision_normalized IS NOT NULL AND revision_order IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_documents_revision_order_range",
        "documents",
        "revision_order IS NULL OR revision_order BETWEEN 0 AND 2147483647",
    )
    op.create_check_constraint(
        "ck_documents_current_revision_complete",
        "documents",
        "revision_status <> 'CURRENT' OR "
        "(document_family_key IS NOT NULL AND revision_normalized IS NOT NULL "
        "AND revision_order IS NOT NULL AND revision_decided_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_documents_historical_revision_complete",
        "documents",
        "revision_status NOT IN ('HISTORICAL', 'DUPLICATE') OR "
        "(document_family_key IS NOT NULL AND revision_normalized IS NOT NULL "
        "AND revision_order IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_documents_revision_decision_timestamp",
        "documents",
        "(revision_status = 'UNASSESSED' AND revision_decided_at IS NULL) OR "
        "(revision_status <> 'UNASSESSED' AND revision_decided_at IS NOT NULL)",
    )
    op.create_index(
        "uq_documents_current_family",
        "documents",
        ["project_id", "category", "document_family_key"],
        unique=True,
        postgresql_where=sa.text(
            "revision_status = 'CURRENT' AND document_family_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_documents_current_family", table_name="documents")
    op.drop_constraint(
        "ck_documents_revision_decision_timestamp", "documents", type_="check"
    )
    op.drop_constraint(
        "ck_documents_historical_revision_complete", "documents", type_="check"
    )
    op.drop_constraint(
        "ck_documents_current_revision_complete", "documents", type_="check"
    )
    op.drop_constraint(
        "ck_documents_revision_pair_complete", "documents", type_="check"
    )
    op.drop_constraint(
        "ck_documents_revision_order_range", "documents", type_="check"
    )
    op.drop_column("documents", "revision_decided_at")
    op.drop_column("documents", "revision_status")
    op.drop_column("documents", "revision_order")
    op.drop_column("documents", "revision_normalized")
    op.drop_column("documents", "revision_label")
    op.drop_column("documents", "document_family_key")
