from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus
from app.models.project import Project
from app.repositories.project import ProjectRepository


def test_create_adds_and_flushes_project_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)

    project = repository.create(
        project_code="PROJ-1",
        name="Example Project",
        normalized_name="example project",
    )

    assert project.project_code == "PROJ-1"
    assert project.status is ProjectStatus.ACTIVE
    session.add.assert_called_once_with(project)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_get_uses_the_project_primary_key() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    project_id = uuid4()
    expected = Project(
        project_code="PROJ-1",
        name="Example Project",
        normalized_name="example project",
    )
    session.get.return_value = expected

    result = repository.get(project_id)

    assert result is expected
    session.get.assert_called_once_with(Project, project_id)


def test_find_by_normalized_codes_is_bounded_to_supplied_exact_codes() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    expected = [
        Project(
            id=uuid4(),
            project_code="PROJ-1",
            name="Example Project",
            normalized_name="example project",
        )
    ]
    session.scalars.return_value.all.return_value = expected

    result = repository.find_by_normalized_codes({"proj-1", "proj-2"})

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1
    assert len(statement._order_by_clauses) == 2
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_find_by_normalized_codes_skips_database_for_empty_input() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)

    assert repository.find_by_normalized_codes(set()) == []
    session.scalars.assert_not_called()


def test_find_by_normalized_names_is_exact_ordered_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    expected = [
        Project(
            id=uuid4(),
            project_code="PROJ-1",
            name="Example Project",
            normalized_name="example project",
        )
    ]
    session.scalars.return_value.all.return_value = expected

    result = repository.find_by_normalized_names({"example project"})

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1
    assert len(statement._order_by_clauses) == 2
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_find_by_normalized_names_skips_empty_input() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)

    assert repository.find_by_normalized_names(set()) == []
    session.scalars.assert_not_called()


def test_list_for_fuzzy_name_retrieval_is_ordered_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    expected = [MagicMock(spec=Project)]
    session.scalars.return_value.all.return_value = expected

    assert repository.list_for_fuzzy_name_retrieval() == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._order_by_clauses) == 2
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_list_all_is_complete_ordered_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    expected = [MagicMock(spec=Project) for _ in range(101)]
    session.scalars.return_value.all.return_value = expected

    assert repository.list_all() == expected

    statement = session.scalars.call_args.args[0]
    assert len(statement._order_by_clauses) == 2
    assert statement._limit_clause is None
    assert statement._offset_clause is None
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_list_returns_filtered_paginated_projects() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    expected = [
        Project(
            project_code="PROJ-1",
            name="Example Project",
            normalized_name="example project",
        )
    ]
    session.scalars.return_value.all.return_value = expected

    result = repository.list(status=ProjectStatus.ACTIVE, offset=10, limit=5)

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert statement._offset_clause.value == 10
    assert statement._limit_clause.value == 5
    assert len(statement._where_criteria) == 1


def test_update_changes_only_provided_fields_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectRepository(session)
    project = Project(
        project_code="PROJ-1",
        name="Old Name",
        normalized_name="old name",
    )

    result = repository.update(
        project,
        name="New Name",
        normalized_name="new name",
        status=ProjectStatus.CLOSED,
    )

    assert result is project
    assert project.project_code == "PROJ-1"
    assert project.name == "New Name"
    assert project.normalized_name == "new name"
    assert project.status is ProjectStatus.CLOSED
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()
