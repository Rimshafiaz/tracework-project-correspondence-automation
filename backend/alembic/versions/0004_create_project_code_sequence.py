"""create project code sequence

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_CODE_SEQUENCE_NAME = "tracework_project_code_seq"


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE SEQUENCE tracework_project_code_seq "
            "AS BIGINT START WITH 1 INCREMENT BY 1 MINVALUE 1 NO CYCLE"
        )
    )
    op.execute(
        sa.text(
            "DO $$ "
            "DECLARE highest_existing_code BIGINT; "
            "BEGIN "
            "SELECT MAX(substring(project_code FROM '^TW-([0-9]+)$')::BIGINT) "
            "INTO highest_existing_code "
            "FROM projects "
            "WHERE project_code ~ '^TW-[0-9]+$'; "
            "IF highest_existing_code IS NULL OR highest_existing_code < 1 THEN "
            "PERFORM setval('tracework_project_code_seq', 1, false); "
            "ELSE "
            "PERFORM setval('tracework_project_code_seq', highest_existing_code, true); "
            "END IF; "
            "END $$"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP SEQUENCE tracework_project_code_seq"))
