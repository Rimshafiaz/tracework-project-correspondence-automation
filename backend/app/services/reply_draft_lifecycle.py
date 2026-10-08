from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from app.contracts.reply_draft import ReplyDraftContent
from app.models.enums import FollowUpStatus, ReplyDraftStatus, ReplyType
from app.models.reply_draft import ReplyDraft
from app.repositories.follow_up import FollowUpRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.repositories.requirement import RequirementRepository


class ReplyDraftLifecycleError(RuntimeError):
    pass


REPLY_DRAFT_SEND_ATTEMPT_NAMESPACE = UUID("d2654dc7-e498-4e9f-966a-1a222d98ed74")


def deterministic_send_attempt_id(reply_draft_id: UUID) -> UUID:
    return uuid5(REPLY_DRAFT_SEND_ATTEMPT_NAMESPACE, str(reply_draft_id))


class ReplyDraftLifecycleService:
    """Guards ReplyDraft state without invoking AI, Gmail, or side effects."""

    def __init__(
        self,
        *,
        session: Session,
        follow_up_repository: FollowUpRepository,
        requirement_repository: RequirementRepository,
        reply_draft_repository: ReplyDraftRepository,
    ) -> None:
        repositories = (
            follow_up_repository,
            requirement_repository,
            reply_draft_repository,
        )
        if any(repository.session is not session for repository in repositories):
            raise ValueError("reply-draft lifecycle repositories must share one session")
        self.session = session
        self.follow_ups = follow_up_repository
        self.requirements = requirement_repository
        self.reply_drafts = reply_draft_repository

    def create_generated(
        self,
        *,
        follow_up_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        reply_type: ReplyType,
        content: ReplyDraftContent,
        ai_proposal_id: UUID | None = None,
        source_correspondence_event_id: UUID | None = None,
        target_correspondence_event_id: UUID | None = None,
        project_contact_id: UUID | None = None,
        recipient_email: str | None = None,
        gmail_thread_id: str | None = None,
        source_gmail_message_id: str | None = None,
    ) -> ReplyDraft:
        follow_up = self.follow_ups.get_for_update(follow_up_id)
        if follow_up is None:
            raise ReplyDraftLifecycleError("follow-up was not found")
        if follow_up.status is not FollowUpStatus.DUE:
            raise ReplyDraftLifecycleError("reply drafts require a due follow-up")
        requirement = self.requirements.get_for_update(requirement_id)
        if requirement is None:
            raise ReplyDraftLifecycleError("requirement was not found")
        if (
            follow_up.project_id != project_id
            or follow_up.requirement_id != requirement_id
            or requirement.project_id != project_id
        ):
            raise ReplyDraftLifecycleError("reply-draft lineage is inconsistent")

        existing = self.reply_drafts.find_active_for_follow_up(
            follow_up_id,
            for_update=True,
        )
        if existing is not None:
            return existing
        return self.reply_drafts.create_generated(
            follow_up_id=follow_up_id,
            project_id=project_id,
            requirement_id=requirement_id,
            reply_type=reply_type,
            generated_subject=content.subject,
            generated_body=content.body,
            ai_proposal_id=ai_proposal_id,
            source_correspondence_event_id=source_correspondence_event_id,
            target_correspondence_event_id=target_correspondence_event_id,
            project_contact_id=project_contact_id,
            recipient_email=recipient_email,
            gmail_thread_id=gmail_thread_id,
            source_gmail_message_id=source_gmail_message_id,
        )

    def edit(self, reply_draft_id: UUID, *, content: ReplyDraftContent) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if draft.status not in (ReplyDraftStatus.GENERATED, ReplyDraftStatus.APPROVED):
            raise ReplyDraftLifecycleError("reply draft cannot be edited in its current state")
        draft.edited_subject = content.subject
        draft.edited_body = content.body
        draft.edited_at = datetime.now(UTC)
        if draft.status is ReplyDraftStatus.APPROVED:
            draft.status = ReplyDraftStatus.GENERATED
            draft.approved_at = None
            draft.approved_by_subject = None
        self.session.flush([draft])
        return draft

    def approve(self, reply_draft_id: UUID, *, operator_subject: str) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if not operator_subject.strip():
            raise ValueError("operator_subject must not be blank")
        if draft.status is ReplyDraftStatus.APPROVED:
            return draft
        if draft.status is not ReplyDraftStatus.GENERATED:
            raise ReplyDraftLifecycleError("only generated drafts can be approved")
        draft.status = ReplyDraftStatus.APPROVED
        draft.approved_at = datetime.now(UTC)
        draft.approved_by_subject = operator_subject.strip()
        self.session.flush([draft])
        return draft

    def reject(self, reply_draft_id: UUID) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if draft.status is ReplyDraftStatus.REJECTED:
            return draft
        if draft.status not in (ReplyDraftStatus.GENERATED, ReplyDraftStatus.APPROVED):
            raise ReplyDraftLifecycleError("reply draft cannot be rejected in its current state")
        draft.status = ReplyDraftStatus.REJECTED
        draft.approved_at = None
        draft.approved_by_subject = None
        draft.rejected_at = datetime.now(UTC)
        self.session.flush([draft])
        return draft

    def begin_send(self, reply_draft_id: UUID) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if draft.status is not ReplyDraftStatus.APPROVED:
            raise ReplyDraftLifecycleError("only approved drafts can begin sending")
        draft.status = ReplyDraftStatus.SEND_PENDING
        draft.send_attempt_id = draft.send_attempt_id or deterministic_send_attempt_id(
            draft.id
        )
        draft.send_attempted_at = datetime.now(UTC)
        self.session.flush([draft])
        return draft

    def record_retryable_failure(self, reply_draft_id: UUID, *, failure_code: str) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if draft.status is not ReplyDraftStatus.SEND_PENDING:
            raise ReplyDraftLifecycleError("only a pending send can fail retryably")
        failure_code = failure_code.strip()
        if not failure_code:
            raise ValueError("failure_code must not be blank")
        draft.status = ReplyDraftStatus.RETRYABLE_FAILURE
        draft.send_failure_code = failure_code
        self.session.flush([draft])
        return draft

    def resume_send(self, reply_draft_id: UUID) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if draft.status is not ReplyDraftStatus.RETRYABLE_FAILURE:
            raise ReplyDraftLifecycleError("only retryable failures can resume sending")
        draft.status = ReplyDraftStatus.SEND_PENDING
        draft.send_failure_code = None
        draft.send_attempted_at = datetime.now(UTC)
        self.session.flush([draft])
        return draft

    def mark_sent(
        self,
        reply_draft_id: UUID,
        *,
        gmail_message_id: str,
        gmail_sent_thread_id: str,
    ) -> ReplyDraft:
        draft = self._locked(reply_draft_id)
        if draft.status is not ReplyDraftStatus.SEND_PENDING:
            raise ReplyDraftLifecycleError("only a pending send can be marked sent")
        if not gmail_message_id.strip() or not gmail_sent_thread_id.strip():
            raise ValueError("Gmail identifiers must not be blank")
        draft.status = ReplyDraftStatus.SENT
        draft.gmail_message_id = gmail_message_id.strip()
        draft.gmail_sent_thread_id = gmail_sent_thread_id.strip()
        draft.sent_at = datetime.now(UTC)
        self.session.flush([draft])
        return draft

    def _locked(self, reply_draft_id: UUID) -> ReplyDraft:
        draft = self.reply_drafts.get_for_update(reply_draft_id)
        if draft is None:
            raise ReplyDraftLifecycleError("reply draft was not found")
        return draft
