from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.adapters.gmail.reply_client import GmailLiveSourceMetadata, GmailRecoverySearch, GmailSendReceipt
from app.contracts.reply_draft_context import FollowUpReplyScope
from app.contracts.reply_draft_send import ReplyDraftSendStatus
from app.core.config import Settings
from app.models.enums import FollowUpStatus, ReplyDraftStatus
from app.services.reply_draft_lifecycle import deterministic_send_attempt_id
from app.services.reply_draft_send import (
    ReplyDraftSendAuthorizationError,
    ReplyDraftSendConfigurationError,
    ReplyDraftSendService,
)
import app.services.reply_draft_send as send_module


def _values(status=ReplyDraftStatus.APPROVED):
    session = MagicMock(spec=Session)
    draft_id = uuid4()
    scope = FollowUpReplyScope(
        follow_up_id=uuid4(), project_id=uuid4(), requirement_id=uuid4(),
        source_correspondence_event_id=uuid4(), trusted_contact_id=uuid4(),
        gmail_message_id="source-message", gmail_thread_id="source-thread",
        originating_state_transition_id=uuid4(), originating_audit_event_id=None,
    )
    draft = SimpleNamespace(
        id=draft_id, follow_up_id=scope.follow_up_id, project_id=scope.project_id,
        requirement_id=scope.requirement_id,
        source_correspondence_event_id=scope.source_correspondence_event_id,
        target_correspondence_event_id=scope.source_correspondence_event_id,
        project_contact_id=scope.trusted_contact_id,
        source_gmail_message_id=scope.gmail_message_id, gmail_thread_id=scope.gmail_thread_id,
        recipient_email="client@example.test", status=status, send_attempt_id=None,
        generated_subject="Programme update", generated_body="Body", edited_subject=None,
        edited_body=None, ai_proposal_id=uuid4(), gmail_message_id=None,
        gmail_sent_thread_id=None,
    )
    contact = SimpleNamespace(id=scope.trusted_contact_id, project_id=scope.project_id, is_active=True, email_normalized="client@example.test")
    source = SimpleNamespace(id=scope.source_correspondence_event_id)
    follow_up = SimpleNamespace(id=scope.follow_up_id, status=FollowUpStatus.DUE, became_due_at=datetime.now(UTC))
    repos = [MagicMock() for _ in range(6)]
    drafts, follow_ups, requirements, correspondence, contacts, lineage = repos
    for repository in repos:
        repository.session = session
    drafts.get_for_update.return_value = draft
    follow_ups.get_for_update.return_value = follow_up
    requirements.get_for_update.return_value = SimpleNamespace(project_id=scope.project_id)
    correspondence.get_for_update.return_value = source
    contacts.get.return_value = contact
    lifecycle = MagicMock(); lifecycle.session = session
    def begin(_):
        draft.status = ReplyDraftStatus.SEND_PENDING
        draft.send_attempt_id = deterministic_send_attempt_id(draft.id)
        return draft
    def resume(_):
        draft.status = ReplyDraftStatus.SEND_PENDING
        return draft
    def fail(_, *, failure_code):
        draft.status = ReplyDraftStatus.RETRYABLE_FAILURE; draft.send_failure_code = failure_code
        return draft
    def sent(_, *, gmail_message_id, gmail_sent_thread_id):
        draft.status = ReplyDraftStatus.SENT; draft.gmail_message_id = gmail_message_id; draft.gmail_sent_thread_id = gmail_sent_thread_id
        return draft
    lifecycle.begin_send.side_effect = begin; lifecycle.resume_send.side_effect = resume
    lifecycle.record_retryable_failure.side_effect = fail; lifecycle.mark_sent.side_effect = sent
    eligibility = MagicMock()
    eligibility.assess.return_value = SimpleNamespace(status="DRAFTABLE", scope=scope)
    settings = Settings(database_url="postgresql+psycopg://example", gmail_reply_message_id_domain="reply.tracework.example")
    service = ReplyDraftSendService(
        session=session, settings=settings, gmail_service=MagicMock(), eligibility_service=eligibility,
        reply_draft_lifecycle=lifecycle, reply_draft_repository=drafts,
        follow_up_repository=follow_ups, requirement_repository=requirements,
        correspondence_repository=correspondence, contact_repository=contacts,
        lineage_repository=lineage,
    )
    # The real service validates the typed enum; focused ownership tests isolate it.
    authorized = SimpleNamespace(draft=draft, scope=scope, contact=contact, source=source, rfc_message_id="<reply@example.test>")
    service._authorize_locked = MagicMock(return_value=authorized)
    return service, draft, scope, lifecycle, session, lineage


def _live(scope):
    return GmailLiveSourceMetadata(
        message_id=scope.gmail_message_id, thread_id=scope.gmail_thread_id,
        rfc_message_id="<source@example.test>", references=None, in_reply_to=None,
        subject="Programme update", sender="Client <client@example.test>",
    )


def test_send_owner_is_the_only_zero_match_request_allowed_to_send(monkeypatch):
    owner, draft, scope, _, _, _ = _values()
    observer, observed, _, _, _, _ = _values(ReplyDraftStatus.SEND_PENDING)
    observed.send_attempt_id = deterministic_send_attempt_id(observed.id)
    monkeypatch.setattr(send_module, "fetch_live_source_metadata", lambda *_: _live(scope))
    monkeypatch.setattr(send_module, "search_sent_by_rfc_message_id", lambda *_args, **_: GmailRecoverySearch((), ()))
    owner._finalize = MagicMock(return_value=SimpleNamespace(status=ReplyDraftSendStatus.SENT_NOW))
    observer._finalize = MagicMock()
    observer._live_source = MagicMock(return_value=_live(scope))
    send = MagicMock(return_value=GmailSendReceipt("sent", scope.gmail_thread_id))
    monkeypatch.setattr(send_module, "send_gmail_reply", send)

    owner_result = owner.send(draft.id, operator_subject="operator")
    observer_result = observer.send(observed.id, operator_subject="operator")

    assert owner_result.status is ReplyDraftSendStatus.SENT_NOW
    assert observer_result.status is ReplyDraftSendStatus.SEND_STILL_PENDING
    send.assert_called_once()


def test_pending_observer_reconciles_one_match_but_never_sends(monkeypatch):
    service, draft, scope, _, _, _ = _values(ReplyDraftStatus.SEND_PENDING)
    draft.send_attempt_id = deterministic_send_attempt_id(draft.id)
    monkeypatch.setattr(send_module, "fetch_live_source_metadata", lambda *_: _live(scope))
    monkeypatch.setattr(send_module, "search_sent_by_rfc_message_id", lambda *_args, **_: GmailRecoverySearch(("sent",), (scope.gmail_thread_id,)))
    send = MagicMock(); monkeypatch.setattr(send_module, "send_gmail_reply", send)
    service._finalize = MagicMock(return_value=SimpleNamespace(status=ReplyDraftSendStatus.RECONCILED_SENT))
    service._live_source = MagicMock(return_value=_live(scope))

    result = service.send(draft.id, operator_subject="operator")

    assert result.status is ReplyDraftSendStatus.RECONCILED_SENT
    send.assert_not_called()


def test_retryable_failure_resumes_as_new_owner_with_stable_attempt_id(monkeypatch):
    service, draft, scope, lifecycle, _, _ = _values(ReplyDraftStatus.RETRYABLE_FAILURE)
    draft.send_attempt_id = deterministic_send_attempt_id(draft.id)
    monkeypatch.setattr(send_module, "fetch_live_source_metadata", lambda *_: _live(scope))
    monkeypatch.setattr(send_module, "search_sent_by_rfc_message_id", lambda *_args, **_: GmailRecoverySearch((), ()))
    monkeypatch.setattr(send_module, "send_gmail_reply", lambda *_: GmailSendReceipt("sent", scope.gmail_thread_id))
    service._finalize = MagicMock(return_value=SimpleNamespace(status=ReplyDraftSendStatus.SENT_NOW))

    service.send(draft.id, operator_subject="operator")

    lifecycle.resume_send.assert_called_once_with(draft.id)
    assert draft.send_attempt_id == deterministic_send_attempt_id(draft.id)


def test_missing_message_id_domain_blocks_before_pending_transition():
    service, draft, _, lifecycle, session, _ = _values()
    service.settings = Settings(database_url="postgresql+psycopg://example")

    with pytest.raises(ReplyDraftSendConfigurationError):
        service.send(draft.id, operator_subject="operator")

    lifecycle.begin_send.assert_not_called()
    session.commit.assert_not_called()


def test_already_sent_requires_consistent_completed_follow_up():
    service, draft, _, _, _, _ = _values(ReplyDraftStatus.SENT)
    draft.gmail_message_id = "sent"
    draft.gmail_sent_thread_id = "thread"
    service.follow_ups.get_for_update.return_value.status = FollowUpStatus.COMPLETED

    result = service.send(draft.id, operator_subject="operator")

    assert result.status is ReplyDraftSendStatus.ALREADY_SENT

    service.follow_ups.get_for_update.return_value.status = FollowUpStatus.DUE
    with pytest.raises(Exception, match="inconsistent follow-up"):
        service.send(draft.id, operator_subject="operator")


def test_finalization_marks_sent_completes_follow_up_and_audits_once():
    service, draft, scope, lifecycle, session, lineage = _values(ReplyDraftStatus.SEND_PENDING)
    draft.send_attempt_id = deterministic_send_attempt_id(draft.id)
    authorized = service._authorize_locked.return_value
    result = service._finalize(
        authorized, gmail_message_id="sent", gmail_thread_id=scope.gmail_thread_id,
        operator_subject="operator", status=ReplyDraftSendStatus.SENT_NOW,
    )

    assert result.status is ReplyDraftSendStatus.SENT_NOW
    lifecycle.mark_sent.assert_called_once()
    service.follow_ups.update_lifecycle.assert_called_once()
    assert lineage.create_audit_event.call_count == 2
    session.commit.assert_called_once()


def test_authorization_error_after_prepare_records_controlled_failure(monkeypatch):
    service, draft, scope, lifecycle, _, _ = _values()
    monkeypatch.setattr(send_module, "fetch_live_source_metadata", lambda *_: (_ for _ in ()).throw(ReplyDraftSendAuthorizationError("mismatch")))

    result = service.send(draft.id, operator_subject="operator")

    assert result.status is ReplyDraftSendStatus.ACTION_REQUIRED
    assert result.failure_code == "GMAIL_AUTHORIZATION_INVALID"
    lifecycle.record_retryable_failure.assert_called_once()
