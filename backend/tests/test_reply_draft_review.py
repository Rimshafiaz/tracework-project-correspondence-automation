from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.reply_draft import ReplyDraftContent
from app.models.enums import ReplyDraftStatus, ReplyType
from app.services.reply_draft_review import (
    REPLY_DRAFT_APPROVED_AUDIT_EVENT,
    REPLY_DRAFT_EDITED_AUDIT_EVENT,
    REPLY_DRAFT_REJECTED_AUDIT_EVENT,
    ReplyDraftReviewService,
)


def _draft(status=ReplyDraftStatus.GENERATED):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(), follow_up_id=uuid4(), project_id=uuid4(), requirement_id=uuid4(),
        ai_proposal_id=uuid4(), source_correspondence_event_id=uuid4(),
        target_correspondence_event_id=None, project_contact_id=uuid4(),
        reply_type=ReplyType.OVERDUE_FOLLOW_UP, generated_subject="Generated",
        generated_body="Generated body", edited_subject=None, edited_body=None,
        status=status, recipient_email="client@example.test", gmail_thread_id="thread",
        source_gmail_message_id="message", approved_at=None, approved_by_subject=None,
        rejected_at=None, send_attempt_id=None, send_attempted_at=None,
        send_failure_code=None, sent_at=None, gmail_message_id=None,
        gmail_sent_thread_id=None, generated_at=now, created_at=now, updated_at=now,
    )


def _service(draft):
    session = MagicMock()
    drafts = MagicMock(); drafts.session = session
    drafts.get.return_value = draft; drafts.get_for_update.return_value = draft
    lifecycle = MagicMock(); lifecycle.session = session
    lifecycle.edit.return_value = draft; lifecycle.approve.return_value = draft; lifecycle.reject.return_value = draft
    lineage = MagicMock(); lineage.session = session
    return ReplyDraftReviewService(session=session, reply_draft_repository=drafts, lifecycle_service=lifecycle, lineage_repository=lineage), lifecycle, lineage


def test_review_service_reads_edit_approves_and_rejects_with_human_audit_attribution():
    draft = _draft()
    service, lifecycle, lineage = _service(draft)

    read = service.get(draft.id)
    service.edit(draft.id, content=ReplyDraftContent(subject="Edited", body="Edited body"), operator_subject="operator")
    service.approve(draft.id, operator_subject="operator")
    service.reject(draft.id, operator_subject="operator")

    assert read.effective.subject == "Generated"
    lifecycle.edit.assert_called_once()
    assert [call.kwargs["event_type"] for call in lineage.create_audit_event.call_args_list] == [
        REPLY_DRAFT_EDITED_AUDIT_EVENT,
        REPLY_DRAFT_APPROVED_AUDIT_EVENT,
        REPLY_DRAFT_REJECTED_AUDIT_EVENT,
    ]
    assert all(call.kwargs["actor_identifier"] == "operator" for call in lineage.create_audit_event.call_args_list)


def test_metadata_failure_allows_only_normal_revalidated_send_retry():
    draft = _draft(ReplyDraftStatus.RETRYABLE_FAILURE)
    draft.send_failure_code = "GMAIL_METADATA_INVALID"
    service, _, _ = _service(draft)

    snapshot = service.get(draft.id)

    assert snapshot.can_retry_send is True
    assert snapshot.can_send is False

    draft.send_failure_code = "GMAIL_AUTHORIZATION_INVALID"
    blocked = service.get(draft.id)

    assert blocked.can_retry_send is False
    assert blocked.send_attention_required is True

    draft.send_failure_code = "GMAIL_SEND_FAILED"
    recovered = service.get(draft.id)

    assert recovered.can_retry_send is True
    assert recovered.send_attention_required is False
