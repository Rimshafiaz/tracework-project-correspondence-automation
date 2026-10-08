from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts.reply_draft import ReplyDraftContent
from app.models.enums import FollowUpStatus, ReplyDraftStatus, ReplyType
from app.repositories.follow_up import FollowUpRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.repositories.requirement import RequirementRepository
from app.services.reply_draft_lifecycle import (
    deterministic_send_attempt_id,
    ReplyDraftLifecycleError,
    ReplyDraftLifecycleService,
)


def _service(*, follow_up_status=FollowUpStatus.DUE):
    session = MagicMock(spec=Session)
    project_id = uuid4()
    requirement_id = uuid4()
    follow_up = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        requirement_id=requirement_id,
        status=follow_up_status,
    )
    requirement = SimpleNamespace(id=requirement_id, project_id=project_id)
    follow_ups = MagicMock(spec=FollowUpRepository)
    requirements = MagicMock(spec=RequirementRepository)
    for repository in (follow_ups, requirements):
        repository.session = session
    follow_ups.get_for_update.return_value = follow_up
    requirements.get_for_update.return_value = requirement
    drafts = []

    class MemoryReplyDraftRepository:
        def __init__(self):
            self.session = session

        def find_active_for_follow_up(self, follow_up_id, *, for_update=False):
            return next(
                (
                    draft
                    for draft in drafts
                    if draft.follow_up_id == follow_up_id
                    and draft.status
                    in {
                        ReplyDraftStatus.GENERATED,
                        ReplyDraftStatus.APPROVED,
                        ReplyDraftStatus.SEND_PENDING,
                        ReplyDraftStatus.RETRYABLE_FAILURE,
                    }
                ),
                None,
            )

        def create_generated(self, **values):
            draft = SimpleNamespace(
                id=uuid4(),
                **values,
                status=ReplyDraftStatus.GENERATED,
                edited_subject=None,
                edited_body=None,
                edited_at=None,
                approved_at=None,
                approved_by_subject=None,
                rejected_at=None,
                send_attempt_id=None,
                send_attempted_at=None,
                send_failure_code=None,
                sent_at=None,
                gmail_message_id=None,
                gmail_sent_thread_id=None,
            )
            drafts.append(draft)
            return draft

        def get_for_update(self, draft_id):
            return next((draft for draft in drafts if draft.id == draft_id), None)

    reply_drafts = MemoryReplyDraftRepository()
    service = ReplyDraftLifecycleService(
        session=session,
        follow_up_repository=follow_ups,
        requirement_repository=requirements,
        reply_draft_repository=reply_drafts,
    )
    return service, follow_up, requirement, drafts, session


def _create(service, follow_up, requirement):
    return service.create_generated(
        follow_up_id=follow_up.id,
        project_id=follow_up.project_id,
        requirement_id=requirement.id,
        reply_type=ReplyType.OVERDUE_FOLLOW_UP,
        content=ReplyDraftContent(
            subject="Requirement follow-up",
            body="Please provide the outstanding requirement.",
        ),
    )


def test_creates_valid_generated_draft_with_follow_up_project_requirement_lineage():
    service, follow_up, requirement, drafts, _ = _service()

    draft = _create(service, follow_up, requirement)

    assert draft.status is ReplyDraftStatus.GENERATED
    assert draft.follow_up_id == follow_up.id
    assert draft.project_id == follow_up.project_id
    assert draft.requirement_id == requirement.id
    assert len(drafts) == 1


def test_duplicate_generation_reuses_active_draft():
    service, follow_up, requirement, drafts, _ = _service()

    first = _create(service, follow_up, requirement)
    second = _create(service, follow_up, requirement)

    assert second is first
    assert len(drafts) == 1


def test_cross_project_or_non_due_lineage_is_rejected():
    service, follow_up, requirement, _, _ = _service()

    with pytest.raises(ReplyDraftLifecycleError, match="lineage is inconsistent"):
        service.create_generated(
            follow_up_id=follow_up.id,
            project_id=uuid4(),
            requirement_id=requirement.id,
            reply_type=ReplyType.OVERDUE_FOLLOW_UP,
            content=ReplyDraftContent(subject="Subject", body="Body"),
        )

    not_due_service, not_due, requirement, _, _ = _service(
        follow_up_status=FollowUpStatus.SCHEDULED
    )
    with pytest.raises(ReplyDraftLifecycleError, match="due follow-up"):
        _create(not_due_service, not_due, requirement)


def test_approved_edit_invalidates_approval_without_overwriting_generated_content():
    service, follow_up, requirement, _, _ = _service()
    draft = _create(service, follow_up, requirement)
    generated = (draft.generated_subject, draft.generated_body)

    service.approve(draft.id, operator_subject="operator")
    edited = service.edit(
        draft.id,
        content=ReplyDraftContent(subject="Edited subject", body="Edited body"),
    )

    assert edited.status is ReplyDraftStatus.GENERATED
    assert edited.approved_at is None
    assert edited.approved_by_subject is None
    assert (edited.generated_subject, edited.generated_body) == generated
    assert (edited.edited_subject, edited.edited_body) == (
        "Edited subject",
        "Edited body",
    )


def test_approved_lifecycle_supports_pending_failure_retry_and_sent_terminal_state():
    service, follow_up, requirement, _, _ = _service()
    draft = _create(service, follow_up, requirement)

    service.approve(draft.id, operator_subject="operator")
    service.begin_send(draft.id)
    assert draft.status is ReplyDraftStatus.SEND_PENDING
    original_attempt_id = draft.send_attempt_id
    assert original_attempt_id == deterministic_send_attempt_id(draft.id)
    service.record_retryable_failure(draft.id, failure_code="GMAIL_UNAVAILABLE")
    assert draft.status is ReplyDraftStatus.RETRYABLE_FAILURE
    service.resume_send(draft.id)
    assert draft.status is ReplyDraftStatus.SEND_PENDING
    assert draft.send_attempt_id == original_attempt_id
    service.mark_sent(
        draft.id,
        gmail_message_id="gmail-message",
        gmail_sent_thread_id="gmail-thread",
    )
    assert draft.status is ReplyDraftStatus.SENT
    assert draft.sent_at is not None

    for action in (
        lambda: service.edit(
            draft.id, content=ReplyDraftContent(subject="No", body="No")
        ),
        lambda: service.approve(draft.id, operator_subject="operator"),
        lambda: service.reject(draft.id),
        lambda: service.begin_send(draft.id),
    ):
        with pytest.raises(ReplyDraftLifecycleError):
            action()


def test_generated_or_rejected_drafts_cannot_send_or_be_approved_after_rejection():
    service, follow_up, requirement, _, _ = _service()
    draft = _create(service, follow_up, requirement)

    with pytest.raises(ReplyDraftLifecycleError, match="approved"):
        service.begin_send(draft.id)
    service.reject(draft.id)
    assert draft.status is ReplyDraftStatus.REJECTED
    with pytest.raises(ReplyDraftLifecycleError, match="generated"):
        service.approve(draft.id, operator_subject="operator")
    with pytest.raises(ReplyDraftLifecycleError, match="approved"):
        service.begin_send(draft.id)
