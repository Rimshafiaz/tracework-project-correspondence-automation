from unittest.mock import MagicMock
from uuid import uuid4

from app.models.enums import ReplyDraftStatus, ReplyType
from app.repositories.reply_draft import ReplyDraftRepository


def test_repository_creates_generated_draft_without_lifecycle_decisions():
    session = MagicMock()
    repository = ReplyDraftRepository(session)

    draft = repository.create_generated(
        follow_up_id=uuid4(),
        project_id=uuid4(),
        requirement_id=uuid4(),
        reply_type=ReplyType.OVERDUE_FOLLOW_UP,
        generated_subject="Subject",
        generated_body="Body",
    )

    assert draft.status is ReplyDraftStatus.GENERATED
    assert draft.ai_proposal_id is None
    session.add.assert_called_once_with(draft)
    session.flush.assert_called_once_with()


def test_active_lookup_is_scoped_to_follow_up_and_can_lock():
    session = MagicMock()
    repository = ReplyDraftRepository(session)

    repository.find_active_for_follow_up(uuid4(), for_update=True)

    statement = session.scalar.call_args.args[0]
    rendered = str(statement)
    assert "reply_drafts.follow_up_id" in rendered
    assert "reply_drafts.status IN" in rendered
    assert statement._for_update_arg is not None
