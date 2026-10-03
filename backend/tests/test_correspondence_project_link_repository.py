from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.correspondence_project_link import CorrespondenceProjectLink
from app.models.project import Project
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository


def test_get_link_uses_primary_key_lookup() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    link_id = uuid4()
    link = MagicMock(spec=CorrespondenceProjectLink)
    session.get.return_value = link

    assert repository.get(link_id) is link
    session.get.assert_called_once_with(CorrespondenceProjectLink, link_id)


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


def test_get_or_create_approved_link_reuses_existing_link() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    existing = MagicMock(spec=CorrespondenceProjectLink)
    session.scalar.return_value = existing

    link, created = repository.get_or_create_approved_link(
        correspondence_event_id=uuid4(),
        project_id=uuid4(),
    )

    assert link is existing
    assert created is False
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_get_or_create_approved_link_creates_when_missing() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    session.scalar.return_value = None

    link, created = repository.get_or_create_approved_link(
        correspondence_event_id=uuid4(),
        project_id=uuid4(),
    )

    assert created is True
    session.add.assert_called_once_with(link)
    session.flush.assert_called_once_with()


def test_event_lookup_returns_current_authoritative_project_ids() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    project_id = uuid4()
    session.scalars.return_value.all.return_value = [project_id]

    result = repository.list_approved_project_ids_for_event(uuid4())

    assert result == [project_id]
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1
    assert len(statement._order_by_clauses) == 1


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


def test_find_approved_projects_for_conversation_is_distinct_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    expected = [MagicMock(spec=Project)]
    session.scalars.return_value.all.return_value = expected

    result = repository.find_approved_projects_for_conversation(
        source="fixture",
        external_conversation_id="conversation-1",
    )

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert len(statement._order_by_clauses) == 2
    assert statement._distinct is True
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_find_approved_projects_for_conversation_skips_blank_identity() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)

    assert repository.find_approved_projects_for_conversation(
        source="",
        external_conversation_id="conversation-1",
    ) == []
    session.scalars.assert_not_called()


def test_find_approved_links_preserves_exact_link_provenance() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceProjectLinkRepository(session)
    expected = [
        (
            MagicMock(spec=CorrespondenceProjectLink),
            MagicMock(spec=Project),
        )
    ]
    session.execute.return_value = expected

    result = repository.find_approved_links_with_projects_for_conversation(
        source="fixture",
        external_conversation_id="conversation-1",
    )

    assert result == expected
    statement = session.execute.call_args.args[0]
    assert len(statement._where_criteria) == 2
    session.flush.assert_not_called()
    session.commit.assert_not_called()
