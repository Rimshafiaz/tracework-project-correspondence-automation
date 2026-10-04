from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.enums import ProjectStatus, RequirementState
from app.repositories.project import ProjectRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.services.project_workspace import (
    ProjectWorkspaceNotFoundError,
    ProjectWorkspaceService,
)


def _project(*, code: str, created_at: datetime):
    return SimpleNamespace(
        id=uuid4(),
        project_code=code,
        name=f"Project {code}",
        status=ProjectStatus.ACTIVE,
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=1),
    )


def _service():
    projects = MagicMock(spec=ProjectRepository)
    identifiers = MagicMock(spec=ProjectIdentifierRepository)
    requirements = MagicMock(spec=RequirementRepository)
    return (
        ProjectWorkspaceService(
            project_repository=projects,
            identifier_repository=identifiers,
            requirement_repository=requirements,
        ),
        projects,
        identifiers,
        requirements,
    )


def test_list_projects_maps_complete_repository_order() -> None:
    service, projects, identifiers, requirements = _service()
    now = datetime.now(UTC)
    project_b = _project(code="B-200", created_at=now)
    project_a = _project(code="A-100", created_at=now + timedelta(seconds=1))
    projects.list_all.return_value = [project_a, project_b]

    result = service.list_projects()

    assert [item.id for item in result] == [project_a.id, project_b.id]
    assert [item.project_code for item in result] == ["A-100", "B-200"]
    projects.list_all.assert_called_once_with()
    identifiers.assert_not_called()
    requirements.assert_not_called()


def test_workspace_maps_identifiers_and_authoritative_requirements() -> None:
    service, projects, identifiers, requirements = _service()
    now = datetime.now(UTC)
    project = _project(code="GEN-1", created_at=now)
    projects.get.return_value = project
    first_identifier = SimpleNamespace(
        id=uuid4(),
        identifier_type="external_reference",
        display_value="External 42",
        normalized_value="external 42",
        verified=True,
    )
    second_identifier = SimpleNamespace(
        id=uuid4(),
        identifier_type="alias",
        display_value="Example Alias",
        normalized_value="example alias",
        verified=False,
    )
    identifiers.list_for_project.return_value = [
        first_identifier,
        second_identifier,
    ]
    first_requirement = SimpleNamespace(
        id=uuid4(),
        name="Provide approval",
        description="Approval must be recorded.",
        state=RequirementState.PARTIAL,
        expected_date=date(2026, 11, 1),
        created_at=now,
        updated_at=now + timedelta(minutes=2),
    )
    second_requirement = SimpleNamespace(
        id=uuid4(),
        name="Complete verification",
        description=None,
        state=RequirementState.OPEN,
        expected_date=None,
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(minutes=3),
    )
    requirements.list_for_project.return_value = [
        first_requirement,
        second_requirement,
    ]

    result = service.get_workspace(project.id)

    assert result.project.id == project.id
    assert [item.id for item in result.identifiers] == [
        first_identifier.id,
        second_identifier.id,
    ]
    assert result.identifiers[0].display_value == "External 42"
    assert not hasattr(result.identifiers[0], "normalized_value")
    assert [item.id for item in result.requirements] == [
        first_requirement.id,
        second_requirement.id,
    ]
    assert result.requirements[0].state is RequirementState.PARTIAL
    assert result.requirements[0].expected_date == date(2026, 11, 1)
    identifiers.list_for_project.assert_called_once_with(project.id)
    requirements.list_for_project.assert_called_once_with(project.id)


def test_unknown_project_stops_before_loading_workspace_children() -> None:
    service, projects, identifiers, requirements = _service()
    project_id = uuid4()
    projects.get.return_value = None

    with pytest.raises(ProjectWorkspaceNotFoundError, match="project was not found"):
        service.get_workspace(project_id)

    identifiers.list_for_project.assert_not_called()
    requirements.list_for_project.assert_not_called()
