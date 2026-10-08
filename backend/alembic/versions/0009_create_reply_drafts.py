"""create reply drafts

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("follow_up_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("ai_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("source_correspondence_event_id", sa.Uuid(), nullable=True),
        sa.Column("target_correspondence_event_id", sa.Uuid(), nullable=True),
        sa.Column("project_contact_id", sa.Uuid(), nullable=True),
        sa.Column(
            "reply_type",
            sa.Enum(
                "ACKNOWLEDGEMENT",
                "CLARIFICATION_REQUEST",
                "OVERDUE_FOLLOW_UP",
                name="reply_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("generated_subject", sa.String(), nullable=False),
        sa.Column("generated_body", sa.Text(), nullable=False),
        sa.Column("edited_subject", sa.String(), nullable=True),
        sa.Column("edited_body", sa.Text(), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "GENERATED",
                "APPROVED",
                "REJECTED",
                "SEND_PENDING",
                "RETRYABLE_FAILURE",
                "SENT",
                name="reply_draft_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("recipient_email", sa.String(), nullable=True),
        sa.Column("gmail_thread_id", sa.String(), nullable=True),
        sa.Column("source_gmail_message_id", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_subject", sa.String(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("send_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_failure_code", sa.String(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gmail_message_id", sa.String(), nullable=True),
        sa.Column("gmail_sent_thread_id", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("btrim(generated_subject) <> ''", name="ck_reply_drafts_generated_subject_not_blank"),
        sa.CheckConstraint("btrim(generated_body) <> ''", name="ck_reply_drafts_generated_body_not_blank"),
        sa.CheckConstraint("(edited_subject IS NULL AND edited_body IS NULL AND edited_at IS NULL) OR (edited_subject IS NOT NULL AND btrim(edited_subject) <> '' AND edited_body IS NOT NULL AND btrim(edited_body) <> '' AND edited_at IS NOT NULL)", name="ck_reply_drafts_edited_content_complete"),
        sa.CheckConstraint("(status = 'GENERATED' AND approved_at IS NULL AND approved_by_subject IS NULL AND rejected_at IS NULL AND send_attempt_id IS NULL AND send_attempted_at IS NULL AND send_failure_code IS NULL AND sent_at IS NULL AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR (status = 'APPROVED' AND approved_at IS NOT NULL AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL AND send_attempt_id IS NULL AND send_attempted_at IS NULL AND send_failure_code IS NULL AND sent_at IS NULL AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR (status = 'REJECTED' AND approved_at IS NULL AND approved_by_subject IS NULL AND rejected_at IS NOT NULL AND send_attempt_id IS NULL AND send_attempted_at IS NULL AND send_failure_code IS NULL AND sent_at IS NULL AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR (status = 'SEND_PENDING' AND approved_at IS NOT NULL AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL AND send_attempt_id IS NOT NULL AND send_attempted_at IS NOT NULL AND send_failure_code IS NULL AND sent_at IS NULL AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR (status = 'RETRYABLE_FAILURE' AND approved_at IS NOT NULL AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL AND send_attempt_id IS NOT NULL AND send_attempted_at IS NOT NULL AND btrim(send_failure_code) <> '' AND sent_at IS NULL AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR (status = 'SENT' AND approved_at IS NOT NULL AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL AND send_attempt_id IS NOT NULL AND send_attempted_at IS NOT NULL AND send_failure_code IS NULL AND sent_at IS NOT NULL AND btrim(gmail_message_id) <> '' AND btrim(gmail_sent_thread_id) <> '')", name="ck_reply_drafts_status_fields"),
        sa.ForeignKeyConstraint(["follow_up_id"], ["follow_ups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_proposal_id"], ["ai_proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_correspondence_event_id"], ["correspondence_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_correspondence_event_id"], ["correspondence_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_contact_id"], ["project_contacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("send_attempt_id", name="uq_reply_drafts_send_attempt_id"),
        sa.UniqueConstraint("gmail_message_id", name="uq_reply_drafts_gmail_message_id"),
    )
    op.create_index("ix_reply_drafts_project_created", "reply_drafts", ["project_id", "created_at"])
    op.create_index("ix_reply_drafts_follow_up_created", "reply_drafts", ["follow_up_id", "created_at"])
    op.create_index("uq_reply_drafts_active_follow_up", "reply_drafts", ["follow_up_id"], unique=True, postgresql_where=sa.text("status IN ('GENERATED', 'APPROVED', 'SEND_PENDING', 'RETRYABLE_FAILURE')"))
    op.create_index("uq_reply_drafts_ai_proposal", "reply_drafts", ["ai_proposal_id"], unique=True, postgresql_where=sa.text("ai_proposal_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("reply_drafts")
