from datetime import UTC, date, datetime
from uuid import uuid4

from app.models.enums import FollowUpCancelReason, FollowUpPurpose, FollowUpStatus
from app.models.follow_up import FollowUp


def _follow_up(**overrides) -> FollowUp:
    values = {
        "project_id": uuid4(),
        "requirement_id": uuid4(),
        "originating_state_transition_id": uuid4(),
        "originating_audit_event_id": None,
        "purpose": FollowUpPurpose.OVERDUE_REQUIREMENT,
        "reason": "The requirement remains outstanding after its expected date.",
        "expected_date": date(2026, 10, 10),
        "due_on": date(2026, 10, 11),
        "status": FollowUpStatus.SCHEDULED,
    }
    values.update(overrides)
    return FollowUp(**values)


def test_follow_up_model_preserves_date_only_schedule_and_stable_s2_identifiers():
    follow_up = _follow_up()

    assert follow_up.expected_date == date(2026, 10, 10)
    assert follow_up.due_on == date(2026, 10, 11)
    assert follow_up.status is FollowUpStatus.SCHEDULED
    assert follow_up.project_id is not None
    assert follow_up.requirement_id is not None
    assert follow_up.originating_state_transition_id is not None


def test_follow_up_model_supports_due_cancelled_and_completed_shapes():
    now = datetime.now(UTC)
    replacement_id = uuid4()

    due = _follow_up(status=FollowUpStatus.DUE, became_due_at=now)
    cancelled = _follow_up(
        status=FollowUpStatus.CANCELLED,
        cancelled_at=now,
        cancel_reason=FollowUpCancelReason.EXPECTED_DATE_CHANGED,
        superseded_by_follow_up_id=replacement_id,
    )
    completed = _follow_up(
        status=FollowUpStatus.COMPLETED,
        became_due_at=now,
        completed_at=now,
    )

    assert due.became_due_at == now
    assert cancelled.superseded_by_follow_up_id == replacement_id
    assert completed.completed_at == now


def test_follow_up_persistence_has_no_agent_email_or_gmail_fields():
    columns = set(FollowUp.__table__.columns.keys())

    assert not {
        "draft_text",
        "recipient",
        "gmail_message_id",
        "agent_state",
        "project_summary",
        "email_history",
        "document_history",
    } & columns


def test_follow_up_table_declares_origin_active_and_schedule_guards():
    constraints = {item.name for item in FollowUp.__table__.constraints}
    indexes = {item.name: item for item in FollowUp.__table__.indexes}

    assert "ck_follow_ups_exactly_one_origin" in constraints
    assert "ck_follow_ups_due_after_expected_date" in constraints
    assert "ck_follow_ups_status_timestamps" in constraints
    assert "ck_follow_ups_supersession_matches_reason" in constraints
    assert indexes["uq_follow_ups_transition_origin"].unique
    assert indexes["uq_follow_ups_audit_origin"].unique
    assert indexes["uq_follow_ups_active_requirement_purpose"].unique
