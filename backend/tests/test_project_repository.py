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
