from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.reply_draft import ReplyDraftContent, ReplyDraftSnapshot
from app.models.reply_draft import ReplyDraft
from app.models.enums import ReplyDraftStatus
from app.repositories.lineage import LineageRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.services.reply_draft_lifecycle import ReplyDraftLifecycleService

REPLY_DRAFT_EDITED_AUDIT_EVENT = "reply_draft_edited"
REPLY_DRAFT_APPROVED_AUDIT_EVENT = "reply_draft_approved"
REPLY_DRAFT_REJECTED_AUDIT_EVENT = "reply_draft_rejected"


class ReplyDraftReviewService:
    """Human-only ReplyDraft edits and decisions with durable attribution."""

    def __init__(
        self,
        *,
        session: Session,
        reply_draft_repository: ReplyDraftRepository,
        lifecycle_service: ReplyDraftLifecycleService,
        lineage_repository: LineageRepository,
    ) -> None:
        if (
            reply_draft_repository.session is not session
            or lifecycle_service.session is not session
            or lineage_repository.session is not session
        ):
            raise ValueError("reply-draft review dependencies must share one session")
        self.session = session
        self.reply_drafts = reply_draft_repository
        self.lifecycle = lifecycle_service
        self.lineage = lineage_repository

    def get(self, reply_draft_id: UUID) -> ReplyDraftSnapshot:
        draft = self.reply_drafts.get(reply_draft_id)
        if draft is None:
            raise LookupError("reply draft was not found")
        return self._snapshot(draft)

    def list_for_project(self, project_id: UUID) -> tuple[ReplyDraftSnapshot, ...]:
        return tuple(self._snapshot(draft) for draft in self.reply_drafts.list_for_project(project_id))

    def edit(
        self,
        reply_draft_id: UUID,
        *,
        content: ReplyDraftContent,
        operator_subject: str,
    ) -> ReplyDraftSnapshot:
        draft = self.lifecycle.edit(reply_draft_id, content=content)
        self._audit(REPLY_DRAFT_EDITED_AUDIT_EVENT, draft, operator_subject)
        return self._snapshot(draft)

    def approve(self, reply_draft_id: UUID, *, operator_subject: str) -> ReplyDraftSnapshot:
        already_approved = self._locked_status_is_approved(reply_draft_id)
        draft = self.lifecycle.approve(reply_draft_id, operator_subject=operator_subject)
        if not already_approved:
            self._audit(REPLY_DRAFT_APPROVED_AUDIT_EVENT, draft, operator_subject)
        return self._snapshot(draft)

    def reject(self, reply_draft_id: UUID, *, operator_subject: str) -> ReplyDraftSnapshot:
        already_rejected = self._locked_status_is_rejected(reply_draft_id)
        draft = self.lifecycle.reject(reply_draft_id)
        if not already_rejected:
            self._audit(REPLY_DRAFT_REJECTED_AUDIT_EVENT, draft, operator_subject)
        return self._snapshot(draft)

    def _locked_status_is_approved(self, reply_draft_id: UUID) -> bool:
        draft = self.reply_drafts.get_for_update(reply_draft_id)
        return bool(draft and draft.status.value == "APPROVED")

    def _locked_status_is_rejected(self, reply_draft_id: UUID) -> bool:
        draft = self.reply_drafts.get_for_update(reply_draft_id)
        return bool(draft and draft.status.value == "REJECTED")

    def _audit(self, event_type: str, draft: ReplyDraft, operator_subject: str) -> None:
        subject = operator_subject.strip()
        if not subject:
            raise ValueError("operator_subject must not be blank")
        self.lineage.create_audit_event(
            event_type=event_type,
            actor_type="authenticated_operator",
            actor_identifier=subject,
            details={"reply_draft_id": str(draft.id)},
            correspondence_event_id=draft.source_correspondence_event_id,
            project_id=draft.project_id,
            requirement_id=draft.requirement_id,
            ai_proposal_id=draft.ai_proposal_id,
        )

    @staticmethod
    def _snapshot(draft: ReplyDraft) -> ReplyDraftSnapshot:
        generated = ReplyDraftContent(
            subject=draft.generated_subject,
            body=draft.generated_body,
        )
        edited = (
            ReplyDraftContent(subject=draft.edited_subject, body=draft.edited_body)
            if draft.edited_subject is not None and draft.edited_body is not None
            else None
        )
        return ReplyDraftSnapshot(
            id=draft.id,
            follow_up_id=draft.follow_up_id,
            project_id=draft.project_id,
            requirement_id=draft.requirement_id,
            ai_proposal_id=draft.ai_proposal_id,
            source_correspondence_event_id=draft.source_correspondence_event_id,
            target_correspondence_event_id=draft.target_correspondence_event_id,
            project_contact_id=draft.project_contact_id,
            reply_type=draft.reply_type,
            generated=generated,
            edited=edited,
            effective=edited or generated,
            status=draft.status,
            recipient_email=draft.recipient_email,
            gmail_thread_id=draft.gmail_thread_id,
            source_gmail_message_id=draft.source_gmail_message_id,
            approved_at=draft.approved_at,
            approved_by_subject=draft.approved_by_subject,
            rejected_at=draft.rejected_at,
            send_attempt_id=draft.send_attempt_id,
            send_attempted_at=draft.send_attempted_at,
            send_failure_code=draft.send_failure_code,
            sent_at=draft.sent_at,
            gmail_message_id=draft.gmail_message_id,
            gmail_sent_thread_id=draft.gmail_sent_thread_id,
            can_edit=draft.status in (
                ReplyDraftStatus.GENERATED,
                ReplyDraftStatus.APPROVED,
            ),
            can_approve=draft.status is ReplyDraftStatus.GENERATED,
            can_reject=draft.status in (
                ReplyDraftStatus.GENERATED,
                ReplyDraftStatus.APPROVED,
            ),
            can_send=draft.status is ReplyDraftStatus.APPROVED,
            can_retry_send=_can_retry_send(draft),
            send_attention_required=(
                draft.status is ReplyDraftStatus.RETRYABLE_FAILURE
                and not _can_retry_send(draft)
            ),
            generated_at=draft.generated_at,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )


def _can_retry_send(draft: ReplyDraft) -> bool:
    if draft.status is not ReplyDraftStatus.RETRYABLE_FAILURE:
        return False
    return (draft.send_failure_code or "") in {
        "GMAIL_HTTP_408",
        "GMAIL_HTTP_429",
        "GMAIL_HTTP_500",
        "GMAIL_HTTP_502",
        "GMAIL_HTTP_503",
        "GMAIL_HTTP_504",
        "GMAIL_TIMEOUT_UNCERTAIN",
        "GMAIL_CONNECTION_UNCERTAIN",
    }
