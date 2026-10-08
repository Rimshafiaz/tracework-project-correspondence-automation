from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any
from uuid import UUID

import httpx
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.adapters.gmail.reply_client import (
    GmailLiveSourceMetadata,
    GmailReplyMetadataError,
    GmailRecoverySearch,
    build_gmail_reply,
    deterministic_rfc_message_id,
    fetch_live_source_metadata,
    normalize_reply_subject,
    search_sent_by_rfc_message_id,
    send_gmail_reply,
)
from app.contracts.reply_draft_context import FollowUpReplyScope, ReplyDraftEligibilityStatus
from app.contracts.reply_draft_send import (
    ReplyDraftSendOwnership,
    ReplyDraftSendResult,
    ReplyDraftSendStatus,
)
from app.core.config import Settings
from app.models.enums import FollowUpStatus, ReplyDraftStatus
from app.normalization.correspondence import normalize_email
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.repositories.requirement import RequirementRepository
from app.services.reply_draft_eligibility import ReplyDraftEligibilityService
from app.services.reply_draft_lifecycle import ReplyDraftLifecycleError, ReplyDraftLifecycleService

REPLY_SENT_AUDIT_EVENT = "reply_sent"
FOLLOW_UP_COMPLETED_AUDIT_EVENT = "follow_up_completed"


class ReplyDraftSendError(RuntimeError):
    pass


class ReplyDraftSendAuthorizationError(ReplyDraftSendError):
    pass


class ReplyDraftSendConfigurationError(ReplyDraftSendError):
    pass


class ReplyDraftSendStateError(ReplyDraftSendError):
    pass


@dataclass(frozen=True)
class _AuthorizedDraft:
    draft: Any
    scope: FollowUpReplyScope
    contact: Any
    source: Any
    rfc_message_id: str


@dataclass(frozen=True)
class _PreparedSend:
    ownership: ReplyDraftSendOwnership
    authorized: _AuthorizedDraft | None
    result: ReplyDraftSendResult | None = None


class ReplyDraftSendService:
    """Human-triggered Gmail delivery with recovery, never AI or API orchestration."""

    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        gmail_service: Any,
        eligibility_service: ReplyDraftEligibilityService,
        reply_draft_lifecycle: ReplyDraftLifecycleService,
        reply_draft_repository: ReplyDraftRepository,
        follow_up_repository: FollowUpRepository,
        requirement_repository: RequirementRepository,
        correspondence_repository: CorrespondenceEventRepository,
        contact_repository: ProjectContactRepository,
        lineage_repository: LineageRepository,
    ) -> None:
        repositories = (
            reply_draft_repository,
            follow_up_repository,
            requirement_repository,
            correspondence_repository,
            contact_repository,
            lineage_repository,
        )
        if any(repository.session is not session for repository in repositories):
            raise ValueError("reply-draft send repositories must share one session")
        if reply_draft_lifecycle.session is not session:
            raise ValueError("reply-draft send lifecycle must share one session")
        self.session = session
        self.settings = settings
        self.gmail = gmail_service
        self.eligibility = eligibility_service
        self.lifecycle = reply_draft_lifecycle
        self.reply_drafts = reply_draft_repository
        self.follow_ups = follow_up_repository
        self.requirements = requirement_repository
        self.correspondence = correspondence_repository
        self.contacts = contact_repository
        self.lineage = lineage_repository

    def send(self, reply_draft_id: UUID, *, operator_subject: str) -> ReplyDraftSendResult:
        operator_subject = operator_subject.strip()
        if not operator_subject:
            raise ValueError("operator_subject must not be blank")
        prepared = self._prepare(reply_draft_id)
        if prepared.result is not None:
            return prepared.result
        assert prepared.authorized is not None
        authorized = prepared.authorized
        try:
            live = self._live_source(authorized)
            recovery, recovered_message_id = self._recovery(authorized)
        except Exception as exc:
            return self._external_failure(prepared, exc)

        if recovery == "ONE_VALID_MATCH":
            return self._finalize(
                authorized,
                gmail_message_id=recovered_message_id,
                gmail_thread_id=authorized.scope.gmail_thread_id,
                operator_subject=operator_subject,
                status=ReplyDraftSendStatus.RECONCILED_SENT,
            )
        if recovery == "AMBIGUOUS_OR_CONFLICTING":
            return self._ambiguous(prepared)
        if prepared.ownership is ReplyDraftSendOwnership.EXISTING_PENDING_ATTEMPT:
            return ReplyDraftSendResult(
                status=ReplyDraftSendStatus.SEND_STILL_PENDING,
                reply_draft_id=reply_draft_id,
            )

        try:
            reply = build_gmail_reply(
                sender_email=self.settings.gmail_account_email or "",
                recipient_email=authorized.contact.email_normalized,
                subject=self._effective_subject(authorized.draft),
                body=self._effective_body(authorized.draft),
                thread_id=authorized.scope.gmail_thread_id,
                source=live,
                rfc_message_id=authorized.rfc_message_id,
            )
            receipt = send_gmail_reply(self.gmail, reply)
        except Exception as exc:
            return self._external_failure(prepared, exc)
        return self._finalize(
            authorized,
            gmail_message_id=receipt.message_id,
            gmail_thread_id=receipt.thread_id,
            operator_subject=operator_subject,
            status=ReplyDraftSendStatus.SENT_NOW,
        )

    def _prepare(self, reply_draft_id: UUID) -> _PreparedSend:
        draft = self.reply_drafts.get_for_update(reply_draft_id)
        if draft is None:
            self.session.rollback()
            raise ReplyDraftSendStateError("reply draft was not found")
        if draft.status is ReplyDraftStatus.SENT:
            result = self._already_sent(draft)
            self.session.rollback()
            return _PreparedSend(ReplyDraftSendOwnership.ALREADY_SENT, None, result)
        if not self.settings.gmail_reply_message_id_domain:
            self.session.rollback()
            raise ReplyDraftSendConfigurationError(
                "GMAIL_REPLY_MESSAGE_ID_DOMAIN is required before sending"
            )
        authorized = self._authorize_locked(draft)
        if draft.status is ReplyDraftStatus.SEND_PENDING:
            self.session.rollback()
            return _PreparedSend(
                ReplyDraftSendOwnership.EXISTING_PENDING_ATTEMPT,
                authorized,
            )
        try:
            if draft.status is ReplyDraftStatus.APPROVED:
                self.lifecycle.begin_send(draft.id)
            elif draft.status is ReplyDraftStatus.RETRYABLE_FAILURE:
                self.lifecycle.resume_send(draft.id)
            else:
                raise ReplyDraftSendStateError("reply draft is not eligible to send")
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return _PreparedSend(ReplyDraftSendOwnership.SEND_OWNER, authorized)

    def _authorize_locked(self, draft) -> _AuthorizedDraft:
        eligibility = self.eligibility.assess(draft.follow_up_id)
        if eligibility.status is not ReplyDraftEligibilityStatus.DRAFTABLE or eligibility.scope is None:
            raise ReplyDraftSendAuthorizationError("reply draft is no longer send-eligible")
        scope = eligibility.scope
        if (
            draft.project_id != scope.project_id
            or draft.requirement_id != scope.requirement_id
            or draft.source_correspondence_event_id != scope.source_correspondence_event_id
            or draft.target_correspondence_event_id != scope.source_correspondence_event_id
            or draft.project_contact_id != scope.trusted_contact_id
            or draft.source_gmail_message_id != scope.gmail_message_id
            or draft.gmail_thread_id != scope.gmail_thread_id
        ):
            raise ReplyDraftSendAuthorizationError("reply draft lineage is no longer consistent")
        follow_up = self.follow_ups.get_for_update(scope.follow_up_id)
        requirement = self.requirements.get_for_update(scope.requirement_id)
        source = self.correspondence.get_for_update(scope.source_correspondence_event_id)
        contact = self.contacts.get(scope.trusted_contact_id)
        if (
            follow_up is None
            or follow_up.status is not FollowUpStatus.DUE
            or requirement is None
            or requirement.project_id != scope.project_id
            or source is None
            or contact is None
            or contact.project_id != scope.project_id
            or not contact.is_active
            or normalize_email(draft.recipient_email or "") != contact.email_normalized
            or (draft.recipient_email or "") != contact.email_normalized
        ):
            raise ReplyDraftSendAuthorizationError("reply draft target is no longer authorized")
        attempt_id = draft.send_attempt_id
        if attempt_id is None and draft.status in (
            ReplyDraftStatus.SEND_PENDING,
            ReplyDraftStatus.RETRYABLE_FAILURE,
        ):
            raise ReplyDraftSendStateError("pending reply draft is missing its send attempt")
        if attempt_id is None:
            from app.services.reply_draft_lifecycle import deterministic_send_attempt_id

            attempt_id = deterministic_send_attempt_id(draft.id)
        return _AuthorizedDraft(
            draft=draft,
            scope=scope,
            contact=contact,
            source=source,
            rfc_message_id=deterministic_rfc_message_id(
                attempt_id,
                self.settings.gmail_reply_message_id_domain or "",
            ),
        )

    def _live_source(self, authorized: _AuthorizedDraft) -> GmailLiveSourceMetadata:
        live = fetch_live_source_metadata(self.gmail, authorized.scope.gmail_message_id)
        if (
            live.message_id != authorized.scope.gmail_message_id
            or live.thread_id != authorized.scope.gmail_thread_id
            or normalize_email(parseaddr(live.sender)[1]) != authorized.contact.email_normalized
            or not live.subject
            or normalize_reply_subject(live.subject)
            != normalize_reply_subject(self._effective_subject(authorized.draft))
        ):
            raise ReplyDraftSendAuthorizationError("live Gmail source does not match reply lineage")
        return live

    def _recovery(self, authorized: _AuthorizedDraft) -> tuple[str, str | None]:
        result: GmailRecoverySearch = search_sent_by_rfc_message_id(
            self.gmail,
            rfc_message_id=authorized.rfc_message_id,
        )
        if not result.message_ids:
            return "ZERO_MATCHES", None
        if (
            len(result.message_ids) == 1
            and result.thread_ids[0] == authorized.scope.gmail_thread_id
        ):
            return "ONE_VALID_MATCH", result.message_ids[0]
        return "AMBIGUOUS_OR_CONFLICTING", None

    def _external_failure(self, prepared: _PreparedSend, exc: Exception) -> ReplyDraftSendResult:
        if prepared.ownership is not ReplyDraftSendOwnership.SEND_OWNER:
            raise exc
        failure_code = self._failure_code(exc)
        try:
            self.lifecycle.record_retryable_failure(
                prepared.authorized.draft.id,
                failure_code=failure_code,
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return ReplyDraftSendResult(
            status=(
                ReplyDraftSendStatus.RETRYABLE_FAILURE
                if self._is_transient_failure(exc)
                else ReplyDraftSendStatus.ACTION_REQUIRED
            ),
            reply_draft_id=prepared.authorized.draft.id,
            failure_code=failure_code,
        )

    def _ambiguous(self, prepared: _PreparedSend) -> ReplyDraftSendResult:
        if prepared.ownership is ReplyDraftSendOwnership.SEND_OWNER:
            return self._external_failure(
                prepared,
                ReplyDraftSendAuthorizationError("Gmail recovery is ambiguous"),
            )
        return ReplyDraftSendResult(
            status=ReplyDraftSendStatus.AMBIGUOUS_RECOVERY,
            reply_draft_id=prepared.authorized.draft.id,
            failure_code="GMAIL_RECOVERY_AMBIGUOUS",
        )

    def _finalize(
        self,
        authorized: _AuthorizedDraft,
        *,
        gmail_message_id: str | None,
        gmail_thread_id: str,
        operator_subject: str,
        status: ReplyDraftSendStatus,
    ) -> ReplyDraftSendResult:
        if not gmail_message_id:
            raise ReplyDraftSendStateError("confirmed Gmail delivery is missing a message id")
        try:
            draft = self.reply_drafts.get_for_update(authorized.draft.id)
            if draft is None:
                raise ReplyDraftSendStateError("reply draft disappeared before finalization")
            if draft.status is ReplyDraftStatus.SENT:
                result = self._already_sent(draft)
                self.session.rollback()
                return result
            if draft.status is not ReplyDraftStatus.SEND_PENDING:
                raise ReplyDraftSendStateError("reply draft is not pending during finalization")
            fresh = self._authorize_locked(draft)
            if fresh.scope != authorized.scope:
                raise ReplyDraftSendAuthorizationError("reply draft scope changed before finalization")
            self.lifecycle.mark_sent(
                draft.id,
                gmail_message_id=gmail_message_id,
                gmail_sent_thread_id=gmail_thread_id,
            )
            follow_up = self.follow_ups.get_for_update(draft.follow_up_id)
            if follow_up is None or follow_up.status is not FollowUpStatus.DUE:
                raise ReplyDraftSendAuthorizationError("follow-up is no longer due")
            from datetime import UTC, datetime

            self.follow_ups.update_lifecycle(
                follow_up,
                status=FollowUpStatus.COMPLETED,
                became_due_at=follow_up.became_due_at,
                completed_at=datetime.now(UTC),
            )
            details = {
                "reply_draft_id": str(draft.id),
                "follow_up_id": str(follow_up.id),
                "gmail_message_id": gmail_message_id,
                "gmail_thread_id": gmail_thread_id,
            }
            self.lineage.create_audit_event(
                event_type=REPLY_SENT_AUDIT_EVENT,
                actor_type="authenticated_operator",
                actor_identifier=operator_subject,
                correspondence_event_id=fresh.scope.source_correspondence_event_id,
                project_id=fresh.scope.project_id,
                requirement_id=fresh.scope.requirement_id,
                ai_proposal_id=draft.ai_proposal_id,
                details=details,
            )
            self.lineage.create_audit_event(
                event_type=FOLLOW_UP_COMPLETED_AUDIT_EVENT,
                actor_type="authenticated_operator",
                actor_identifier=operator_subject,
                correspondence_event_id=fresh.scope.source_correspondence_event_id,
                project_id=fresh.scope.project_id,
                requirement_id=fresh.scope.requirement_id,
                ai_proposal_id=draft.ai_proposal_id,
                details=details,
            )
            self.session.commit()
            return ReplyDraftSendResult(
                status=status,
                reply_draft_id=draft.id,
                gmail_message_id=gmail_message_id,
                gmail_thread_id=gmail_thread_id,
            )
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _effective_subject(draft) -> str:
        return draft.edited_subject or draft.generated_subject

    @staticmethod
    def _effective_body(draft) -> str:
        return draft.edited_body or draft.generated_body

    @staticmethod
    def _failure_code(exc: Exception) -> str:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status is None:
            status = getattr(exc, "status_code", None)
        if status in {408, 429, 500, 502, 503, 504}:
            return f"GMAIL_HTTP_{status}"
        if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
            return "GMAIL_TIMEOUT_UNCERTAIN"
        if isinstance(exc, (httpx.NetworkError, ConnectionError)):
            return "GMAIL_CONNECTION_UNCERTAIN"
        if isinstance(exc, HttpError):
            return f"GMAIL_HTTP_{status or 'ERROR'}"
        if isinstance(exc, GmailReplyMetadataError):
            return "GMAIL_METADATA_INVALID"
        if isinstance(exc, ReplyDraftSendAuthorizationError):
            return "GMAIL_AUTHORIZATION_INVALID"
        return "GMAIL_SEND_FAILED"

    @staticmethod
    def _is_transient_failure(exc: Exception) -> bool:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status is None:
            status = getattr(exc, "status_code", None)
        return status in {408, 429, 500, 502, 503, 504} or isinstance(
            exc,
            (httpx.TimeoutException, TimeoutError, httpx.NetworkError, ConnectionError),
        )

    def _already_sent(self, draft) -> ReplyDraftSendResult:
        if draft.gmail_message_id is None or draft.gmail_sent_thread_id is None:
            raise ReplyDraftSendStateError("sent reply draft is missing Gmail delivery identity")
        follow_up = self.follow_ups.get_for_update(draft.follow_up_id)
        if follow_up is None or follow_up.status is not FollowUpStatus.COMPLETED:
            raise ReplyDraftSendStateError("sent reply draft has inconsistent follow-up completion")
        return ReplyDraftSendResult(
            status=ReplyDraftSendStatus.ALREADY_SENT,
            reply_draft_id=draft.id,
            gmail_message_id=draft.gmail_message_id,
            gmail_thread_id=draft.gmail_sent_thread_id,
        )
