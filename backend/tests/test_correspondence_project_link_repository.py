from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository


def test_create_approved_link_flushes_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    event_id = uuid4()
    project_id = uuid4()

    link = repository.create_approved_link(
        correspondence_event_id=event_id,
        project_id=project_id,
    )

    assert link.correspondence_event_id == event_id
    assert link.project_id == project_id
    session.add.assert_called_once_with(link)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_conversation_lookup_is_source_scoped_and_distinct() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    project_id = uuid4()
    session.scalars.return_value.all.return_value = [project_id]

    result = repository.list_approved_project_ids_for_conversation(
        source="gmail",
        external_conversation_id="thread-1",
    )

    assert result == [project_id]
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert statement._distinct is True


def test_blank_conversation_identity_never_runs_a_lookup() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)

    assert (
        repository.list_approved_project_ids_for_conversation(
            source="gmail",
            external_conversation_id=" ",
        )
        == []
    )
    session.scalars.assert_not_called()


def test_unique_lookup_returns_only_one_unambiguous_project() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    project_id = uuid4()
    session.scalars.return_value.all.return_value = [project_id]

    assert (
        repository.get_unique_approved_project_id_for_conversation(
            source="gmail",
            external_conversation_id="thread-1",
        )
        == project_id
    )

    session.scalars.return_value.all.return_value = [project_id, uuid4()]
    assert (
        repository.get_unique_approved_project_id_for_conversation(
            source="gmail",
            external_conversation_id="thread-1",
        )
        is None
    )
