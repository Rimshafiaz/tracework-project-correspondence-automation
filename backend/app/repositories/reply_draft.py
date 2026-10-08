from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ReplyDraftStatus, ReplyType
from app.models.reply_draft import ReplyDraft


class ReplyDraftRepository:
    """Mechanical persistence operations for durable reply drafts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, reply_draft_id: UUID) -> ReplyDraft | None:
        return self.session.get(ReplyDraft, reply_draft_id)

    def get_for_update(self, reply_draft_id: UUID) -> ReplyDraft | None:
        return self.session.scalar(
            select(ReplyDraft)
            .where(ReplyDraft.id == reply_draft_id)
            .with_for_update()
        )

    def find_active_for_follow_up(
        self,
        follow_up_id: UUID,
        *,
        for_update: bool = False,
    ) -> ReplyDraft | None:
        statement = select(ReplyDraft).where(
            ReplyDraft.follow_up_id == follow_up_id,
            ReplyDraft.status.in_(
                (
                    ReplyDraftStatus.GENERATED,
                    ReplyDraftStatus.APPROVED,
                    ReplyDraftStatus.SEND_PENDING,
                    ReplyDraftStatus.RETRYABLE_FAILURE,
                )
            ),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_for_follow_up(self, follow_up_id: UUID) -> Sequence[ReplyDraft]:
        return self.session.scalars(
            select(ReplyDraft)
            .where(ReplyDraft.follow_up_id == follow_up_id)
            .order_by(ReplyDraft.created_at, ReplyDraft.id)
        ).all()

    def list_for_project(self, project_id: UUID) -> Sequence[ReplyDraft]:
        return self.session.scalars(
            select(ReplyDraft)
            .where(ReplyDraft.project_id == project_id)
            .order_by(ReplyDraft.created_at.desc(), ReplyDraft.id.desc())
        ).all()

    def create_generated(
        self,
        *,
        follow_up_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        reply_type: ReplyType,
        generated_subject: str,
        generated_body: str,
        ai_proposal_id: UUID | None = None,
        source_correspondence_event_id: UUID | None = None,
        target_correspondence_event_id: UUID | None = None,
        project_contact_id: UUID | None = None,
        recipient_email: str | None = None,
        gmail_thread_id: str | None = None,
        source_gmail_message_id: str | None = None,
    ) -> ReplyDraft:
        draft = ReplyDraft(
            follow_up_id=follow_up_id,
            project_id=project_id,
            requirement_id=requirement_id,
            ai_proposal_id=ai_proposal_id,
            source_correspondence_event_id=source_correspondence_event_id,
            target_correspondence_event_id=target_correspondence_event_id,
            project_contact_id=project_contact_id,
            reply_type=reply_type,
            generated_subject=generated_subject,
            generated_body=generated_body,
            status=ReplyDraftStatus.GENERATED,
            recipient_email=recipient_email,
            gmail_thread_id=gmail_thread_id,
            source_gmail_message_id=source_gmail_message_id,
        )
        self.session.add(draft)
        self.session.flush()
        return draft
