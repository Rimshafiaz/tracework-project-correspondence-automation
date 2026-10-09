"""add requirement retraction state and follow-up cancellation reason

Revision ID: 0011
Revises: 0010
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("requirement_state", "requirements", type_="check")
    op.create_check_constraint(
        "requirement_state", "requirements",
        "state IN ('OPEN', 'PARTIAL', 'SATISFIED', 'REVIEW', 'RETRACTED')",
    )
    op.drop_constraint("follow_up_cancel_reason", "follow_ups", type_="check")
    op.create_check_constraint(
        "follow_up_cancel_reason", "follow_ups",
        "cancel_reason IN ('REQUIREMENT_SATISFIED', 'EXPECTED_DATE_CHANGED', "
        "'EXPECTED_DATE_REMOVED', 'REQUIREMENT_RETRACTED')",
    )


def downgrade() -> None:
    op.drop_constraint("follow_up_cancel_reason", "follow_ups", type_="check")
    op.create_check_constraint(
        "follow_up_cancel_reason", "follow_ups",
        "cancel_reason IN ('REQUIREMENT_SATISFIED', 'EXPECTED_DATE_CHANGED', 'EXPECTED_DATE_REMOVED')",
    )
    op.drop_constraint("requirement_state", "requirements", type_="check")
    op.create_check_constraint(
        "requirement_state", "requirements",
        "state IN ('OPEN', 'PARTIAL', 'SATISFIED', 'REVIEW')",
    )
