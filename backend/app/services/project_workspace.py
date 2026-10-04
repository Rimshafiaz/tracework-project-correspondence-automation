from uuid import UUID

from app.contracts.project_workspace import (
    ProjectSummary,
    ProjectWorkspace,
    ProjectWorkspaceIdentifier,
    ProjectWorkspaceRequirement,
)
from app.repositories.project import ProjectRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository


class ProjectWorkspaceNotFoundError(LookupError):
    pass


class ProjectWorkspaceService:
    def __init__(
        self,
        *,
        project_repository: ProjectRepository,
        identifier_repository: ProjectIdentifierRepository,
        requirement_repository: RequirementRepository,
    ) -> None:
        self.project_repository = project_repository
        self.identifier_repository = identifier_repository
        self.requirement_repository = requirement_repository

    def list_projects(self) -> tuple[ProjectSummary, ...]:
        return tuple(
            self._project_summary(project)
            for project in self.project_repository.list_all()
        )

    def get_workspace(self, project_id: UUID) -> ProjectWorkspace:
        project = self.project_repository.get(project_id)
        if project is None:
            raise ProjectWorkspaceNotFoundError("project was not found")

        identifiers = self.identifier_repository.list_for_project(project_id)
        requirements = self.requirement_repository.list_for_project(project_id)
        return ProjectWorkspace(
            project=self._project_summary(project),
            identifiers=tuple(
                ProjectWorkspaceIdentifier(
                    id=identifier.id,
                    identifier_type=identifier.identifier_type,
                    display_value=identifier.display_value,
                    verified=identifier.verified,
                )
                for identifier in identifiers
            ),
            requirements=tuple(
                ProjectWorkspaceRequirement(
                    id=requirement.id,
                    name=requirement.name,
                    description=requirement.description,
                    state=requirement.state,
                    expected_date=requirement.expected_date,
                    created_at=requirement.created_at,
                    updated_at=requirement.updated_at,
                )
                for requirement in requirements
            ),
        )

    @staticmethod
    def _project_summary(project) -> ProjectSummary:
        return ProjectSummary(
            id=project.id,
            project_code=project.project_code,
            name=project.name,
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
