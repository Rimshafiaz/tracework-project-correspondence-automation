from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.project_identifier import ProjectIdentifier
from app.models.project import Project
from app.repositories.project_identifier import ProjectIdentifierRepository


def test_create_adds_and_flushes_unverified_identifier() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    project_id = uuid4()

    identifier = repository.create(
        project_id=project_id,
        identifier_type="external_id",
        display_value="External 123",
        normalized_value="external 123",
    )

    assert identifier.project_id == project_id
    assert identifier.verified is False
    session.add.assert_called_once_with(identifier)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_get_uses_the_identifier_primary_key() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    identifier_id = uuid4()
    expected = MagicMock(spec=ProjectIdentifier)
    session.get.return_value = expected

    result = repository.get(identifier_id)

    assert result is expected
    session.get.assert_called_once_with(ProjectIdentifier, identifier_id)


def test_list_for_project_scopes_the_query() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    expected = [MagicMock(spec=ProjectIdentifier)]
    session.scalars.return_value.all.return_value = expected

    result = repository.list_for_project(uuid4())

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1


def test_find_exact_requires_verified_identifiers_by_default() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    expected = [MagicMock(spec=ProjectIdentifier)]
    session.scalars.return_value.all.return_value = expected

    result = repository.find_exact(
        identifier_type="external_id",
        normalized_value="external 123",
    )

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 3


def test_find_exact_can_include_unverified_identifiers() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)

    repository.find_exact(
        identifier_type="external_id",
        normalized_value="external 123",
        verified_only=False,
    )

    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 2


def test_find_verified_exact_with_projects_uses_one_read_only_query() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    identifier = MagicMock(spec=ProjectIdentifier)
    project = MagicMock(spec=Project)
    session.execute.return_value = [(identifier, project)]

    result = repository.find_verified_exact_with_projects(
        {("repository", "example/platform"), ("client_ref", "client-1")}
    )

    assert result == [(identifier, project)]
    statement = session.execute.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert len(statement._order_by_clauses) == 5
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_find_verified_exact_with_projects_skips_empty_input() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)

    assert repository.find_verified_exact_with_projects(set()) == []
    session.execute.assert_not_called()


def test_list_verified_type_with_projects_is_filtered_ordered_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    identifier = MagicMock(spec=ProjectIdentifier)
    project = MagicMock(spec=Project)
    session.execute.return_value = [(identifier, project)]

    result = repository.list_verified_type_with_projects("alias")

    assert result == [(identifier, project)]
    statement = session.execute.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert len(statement._order_by_clauses) == 4
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_update_changes_only_provided_fields_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectIdentifierRepository(session)
    identifier = ProjectIdentifier(
        project_id=uuid4(),
        identifier_type="external_id",
        display_value="Old Value",
        normalized_value="old value",
        verified=False,
    )

    result = repository.update(identifier, verified=True)

    assert result is identifier
    assert identifier.display_value == "Old Value"
    assert identifier.normalized_value == "old value"
    assert identifier.verified is True
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()
