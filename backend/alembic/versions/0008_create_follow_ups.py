"""create follow ups

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follow_ups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("originating_state_transition_id", sa.Uuid(), nullable=True),
        sa.Column("originating_audit_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "purpose",
            sa.Enum("OVERDUE_REQUIREMENT", name="follow_up_purpose", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("SCHEDULED", "DUE", "CANCELLED", "COMPLETED", name="follow_up_status", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("superseded_by_follow_up_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_reason",
            sa.Enum("REQUIREMENT_SATISFIED", "EXPECTED_DATE_CHANGED", "EXPECTED_DATE_REMOVED", name="follow_up_cancel_reason", native_enum=False, create_constraint=True),
            nullable=True,
        ),
        sa.Column("became_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_follow_ups_reason_not_blank"),
        sa.CheckConstraint("(originating_state_transition_id IS NOT NULL AND originating_audit_event_id IS NULL) OR (originating_state_transition_id IS NULL AND originating_audit_event_id IS NOT NULL)", name="ck_follow_ups_exactly_one_origin"),
        sa.CheckConstraint("due_on = expected_date + 1", name="ck_follow_ups_due_after_expected_date"),
        sa.CheckConstraint("(status = 'SCHEDULED' AND became_due_at IS NULL AND cancelled_at IS NULL AND cancel_reason IS NULL AND completed_at IS NULL) OR (status = 'DUE' AND became_due_at IS NOT NULL AND cancelled_at IS NULL AND cancel_reason IS NULL AND completed_at IS NULL) OR (status = 'CANCELLED' AND cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND completed_at IS NULL) OR (status = 'COMPLETED' AND became_due_at IS NOT NULL AND cancelled_at IS NULL AND cancel_reason IS NULL AND completed_at IS NOT NULL)", name="ck_follow_ups_status_timestamps"),
        sa.CheckConstraint("(cancel_reason = 'EXPECTED_DATE_CHANGED' AND superseded_by_follow_up_id IS NOT NULL) OR (cancel_reason IS DISTINCT FROM 'EXPECTED_DATE_CHANGED' AND superseded_by_follow_up_id IS NULL)", name="ck_follow_ups_supersession_matches_reason"),
        sa.CheckConstraint("superseded_by_follow_up_id IS NULL OR superseded_by_follow_up_id <> id", name="ck_follow_ups_not_self_superseded"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["originating_state_transition_id"], ["state_transitions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["originating_audit_event_id"], ["audit_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["superseded_by_follow_up_id"],
            ["follow_ups.id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_follow_ups_project_created", "follow_ups", ["project_id", "created_at"])
    op.create_index("ix_follow_ups_requirement_created", "follow_ups", ["requirement_id", "created_at"])
    op.create_index("ix_follow_ups_status_due", "follow_ups", ["status", "due_on", "id"])
    op.create_index("uq_follow_ups_transition_origin", "follow_ups", ["originating_state_transition_id", "requirement_id", "purpose"], unique=True, postgresql_where=sa.text("originating_state_transition_id IS NOT NULL"))
    op.create_index("uq_follow_ups_audit_origin", "follow_ups", ["originating_audit_event_id", "requirement_id", "purpose"], unique=True, postgresql_where=sa.text("originating_audit_event_id IS NOT NULL"))
    op.create_index("uq_follow_ups_active_requirement_purpose", "follow_ups", ["requirement_id", "purpose"], unique=True, postgresql_where=sa.text("status IN ('SCHEDULED', 'DUE')"))


def downgrade() -> None:
    op.drop_table("follow_ups")
