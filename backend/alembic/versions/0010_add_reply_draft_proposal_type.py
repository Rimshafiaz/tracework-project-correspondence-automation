"""add reply draft proposal type

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("proposal_type", "ai_proposals", type_="check")
    op.create_check_constraint(
        "proposal_type",
        "ai_proposals",
        "proposal_type IN ("
        "'PROJECT_RESOLUTION', "
        "'REQUIREMENT_RECONCILIATION', "
        "'RETRACTION_CORRECTION', "
        "'REPLY_DRAFT'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("proposal_type", "ai_proposals", type_="check")
    op.create_check_constraint(
        "proposal_type",
        "ai_proposals",
        "proposal_type IN ("
        "'PROJECT_RESOLUTION', "
        "'REQUIREMENT_RECONCILIATION', "
        "'RETRACTION_CORRECTION'"
        ")",
    )
