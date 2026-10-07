"""add document revision review type

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("review_type", "review_items", type_="check")
    op.create_check_constraint(
        "review_type",
        "review_items",
        "review_type IN ('PROJECT_RESOLUTION', 'REQUIREMENT_CHANGE', "
        "'NEW_REQUIREMENT', 'RETRACTION_CORRECTION', 'DOCUMENT_REVISION')",
    )


def downgrade() -> None:
    op.drop_constraint("review_type", "review_items", type_="check")
    op.create_check_constraint(
        "review_type",
        "review_items",
        "review_type IN ('PROJECT_RESOLUTION', 'REQUIREMENT_CHANGE', "
        "'NEW_REQUIREMENT', 'RETRACTION_CORRECTION')",
    )
