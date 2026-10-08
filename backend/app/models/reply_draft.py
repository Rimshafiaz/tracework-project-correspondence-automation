from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ReplyDraftStatus, ReplyType

if TYPE_CHECKING:
    from app.models.ai_proposal import AIProposal
    from app.models.correspondence_event import CorrespondenceEvent
    from app.models.follow_up import FollowUp
    from app.models.project import Project
    from app.models.project_contact import ProjectContact
    from app.models.requirement import Requirement


class ReplyDraft(Base):
    """A human-approved outbound reply record, never authoritative project state."""

    __tablename__ = "reply_drafts"
    __table_args__ = (
        CheckConstraint(
            "btrim(generated_subject) <> ''",
            name="ck_reply_drafts_generated_subject_not_blank",
        ),
        CheckConstraint(
            "btrim(generated_body) <> ''",
            name="ck_reply_drafts_generated_body_not_blank",
        ),
        CheckConstraint(
            "(edited_subject IS NULL AND edited_body IS NULL AND edited_at IS NULL) OR "
            "(edited_subject IS NOT NULL AND btrim(edited_subject) <> '' "
            "AND edited_body IS NOT NULL AND btrim(edited_body) <> '' "
            "AND edited_at IS NOT NULL)",
            name="ck_reply_drafts_edited_content_complete",
        ),
        CheckConstraint(
            "(status = 'GENERATED' AND approved_at IS NULL "
            "AND approved_by_subject IS NULL AND rejected_at IS NULL "
            "AND send_attempt_id IS NULL AND send_attempted_at IS NULL "
            "AND send_failure_code IS NULL AND sent_at IS NULL "
            "AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR "
            "(status = 'APPROVED' AND approved_at IS NOT NULL "
            "AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL "
            "AND send_attempt_id IS NULL AND send_attempted_at IS NULL "
            "AND send_failure_code IS NULL AND sent_at IS NULL "
            "AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR "
            "(status = 'REJECTED' AND approved_at IS NULL "
            "AND approved_by_subject IS NULL AND rejected_at IS NOT NULL "
            "AND send_attempt_id IS NULL AND send_attempted_at IS NULL "
            "AND send_failure_code IS NULL AND sent_at IS NULL "
            "AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR "
            "(status = 'SEND_PENDING' AND approved_at IS NOT NULL "
            "AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL "
            "AND send_attempt_id IS NOT NULL AND send_attempted_at IS NOT NULL "
            "AND send_failure_code IS NULL AND sent_at IS NULL "
            "AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR "
            "(status = 'RETRYABLE_FAILURE' AND approved_at IS NOT NULL "
            "AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL "
            "AND send_attempt_id IS NOT NULL AND send_attempted_at IS NOT NULL "
            "AND btrim(send_failure_code) <> '' AND sent_at IS NULL "
            "AND gmail_message_id IS NULL AND gmail_sent_thread_id IS NULL) OR "
            "(status = 'SENT' AND approved_at IS NOT NULL "
            "AND btrim(approved_by_subject) <> '' AND rejected_at IS NULL "
            "AND send_attempt_id IS NOT NULL AND send_attempted_at IS NOT NULL "
            "AND send_failure_code IS NULL AND sent_at IS NOT NULL "
            "AND btrim(gmail_message_id) <> '' "
            "AND btrim(gmail_sent_thread_id) <> '')",
            name="ck_reply_drafts_status_fields",
        ),
        Index("ix_reply_drafts_project_created", "project_id", "created_at"),
        Index("ix_reply_drafts_follow_up_created", "follow_up_id", "created_at"),
        Index(
            "uq_reply_drafts_active_follow_up",
            "follow_up_id",
            unique=True,
            postgresql_where=text(
                "status IN ('GENERATED', 'APPROVED', 'SEND_PENDING', 'RETRYABLE_FAILURE')"
            ),
        ),
        Index(
            "uq_reply_drafts_ai_proposal",
            "ai_proposal_id",
            unique=True,
            postgresql_where=text("ai_proposal_id IS NOT NULL"),
        ),
        UniqueConstraint("send_attempt_id", name="uq_reply_drafts_send_attempt_id"),
        UniqueConstraint("gmail_message_id", name="uq_reply_drafts_gmail_message_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    follow_up_id: Mapped[UUID] = mapped_column(
        ForeignKey("follow_ups.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    ai_proposal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_proposals.id", ondelete="RESTRICT")
    )
    source_correspondence_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    target_correspondence_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    project_contact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_contacts.id", ondelete="RESTRICT")
    )
    reply_type: Mapped[ReplyType] = mapped_column(
        Enum(
            ReplyType,
            name="reply_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    generated_subject: Mapped[str] = mapped_column(String)
    generated_body: Mapped[str] = mapped_column(Text)
    edited_subject: Mapped[str | None] = mapped_column(String)
    edited_body: Mapped[str | None] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ReplyDraftStatus] = mapped_column(
        Enum(
            ReplyDraftStatus,
            name="reply_draft_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ReplyDraftStatus.GENERATED,
    )
    recipient_email: Mapped[str | None] = mapped_column(String)
    gmail_thread_id: Mapped[str | None] = mapped_column(String)
    source_gmail_message_id: Mapped[str | None] = mapped_column(String)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_subject: Mapped[str | None] = mapped_column(String)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_attempt_id: Mapped[UUID | None] = mapped_column(Uuid)
    send_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_failure_code: Mapped[str | None] = mapped_column(String)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gmail_message_id: Mapped[str | None] = mapped_column(String)
    gmail_sent_thread_id: Mapped[str | None] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    follow_up: Mapped["FollowUp"] = relationship(back_populates="reply_drafts")
    project: Mapped["Project"] = relationship(back_populates="reply_drafts")
    requirement: Mapped["Requirement"] = relationship(back_populates="reply_drafts")
    ai_proposal: Mapped["AIProposal | None"] = relationship(back_populates="reply_drafts")
    source_correspondence_event: Mapped["CorrespondenceEvent | None"] = relationship(
        foreign_keys=[source_correspondence_event_id],
        back_populates="source_reply_drafts",
    )
    target_correspondence_event: Mapped["CorrespondenceEvent | None"] = relationship(
        foreign_keys=[target_correspondence_event_id],
        back_populates="target_reply_drafts",
    )
    project_contact: Mapped["ProjectContact | None"] = relationship(
        back_populates="reply_drafts"
    )
