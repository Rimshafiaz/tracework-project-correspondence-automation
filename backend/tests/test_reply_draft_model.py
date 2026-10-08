from datetime import UTC, datetime
from uuid import uuid4

from app.models.enums import ReplyDraftStatus, ReplyType
from app.models.reply_draft import ReplyDraft


def _draft(**overrides) -> ReplyDraft:
    values = {
        "follow_up_id": uuid4(),
        "project_id": uuid4(),
        "requirement_id": uuid4(),
        "reply_type": ReplyType.OVERDUE_FOLLOW_UP,
        "generated_subject": "Requirement follow-up",
        "generated_body": "Please provide the outstanding item.",
        "status": ReplyDraftStatus.GENERATED,
    }
    values.update(overrides)
    return ReplyDraft(**values)


def test_generated_draft_preserves_separate_original_and_editable_content_fields():
    draft = _draft()

    assert draft.generated_subject == "Requirement follow-up"
    assert draft.generated_body == "Please provide the outstanding item."
    assert draft.edited_subject is None
    assert draft.edited_body is None


def test_model_supports_all_approved_s2_lifecycle_shapes():
    now = datetime.now(UTC)
    approved = _draft(
        status=ReplyDraftStatus.APPROVED,
        approved_at=now,
        approved_by_subject="operator",
    )
    rejected = _draft(status=ReplyDraftStatus.REJECTED, rejected_at=now)
    pending = _draft(
        status=ReplyDraftStatus.SEND_PENDING,
        approved_at=now,
        approved_by_subject="operator",
        send_attempt_id=uuid4(),
        send_attempted_at=now,
    )
    failed = _draft(
        status=ReplyDraftStatus.RETRYABLE_FAILURE,
        approved_at=now,
        approved_by_subject="operator",
        send_attempt_id=uuid4(),
        send_attempted_at=now,
        send_failure_code="GMAIL_UNAVAILABLE",
    )
    sent = _draft(
        status=ReplyDraftStatus.SENT,
        approved_at=now,
        approved_by_subject="operator",
        send_attempt_id=uuid4(),
        send_attempted_at=now,
        sent_at=now,
        gmail_message_id="gmail-message",
        gmail_sent_thread_id="gmail-thread",
    )

    assert approved.approved_by_subject == "operator"
    assert rejected.rejected_at == now
    assert pending.send_attempt_id is not None
    assert failed.send_failure_code == "GMAIL_UNAVAILABLE"
    assert sent.gmail_message_id == "gmail-message"


def test_reply_draft_table_declares_content_status_and_active_draft_guards():
    constraints = {item.name for item in ReplyDraft.__table__.constraints}
    indexes = {item.name: item for item in ReplyDraft.__table__.indexes}

    assert "ck_reply_drafts_generated_subject_not_blank" in constraints
    assert "ck_reply_drafts_generated_body_not_blank" in constraints
    assert "ck_reply_drafts_edited_content_complete" in constraints
    assert "ck_reply_drafts_status_fields" in constraints
    assert indexes["uq_reply_drafts_active_follow_up"].unique
    assert indexes["uq_reply_drafts_ai_proposal"].unique
