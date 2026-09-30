from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus
from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        project_code: str,
        name: str,
        normalized_name: str,
        status: ProjectStatus = ProjectStatus.ACTIVE,
    ) -> Project:
        project = Project(
            project_code=project_code,
            name=name,
            normalized_name=normalized_name,
            status=status,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, project_id: UUID) -> Project | None:
        return self.session.get(Project, project_id)

    def get_by_code(self, project_code: str) -> Project | None:
        statement = select(Project).where(Project.project_code == project_code)
        return self.session.scalar(statement)

    def list(
        self,
        *,
        status: ProjectStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Project]:
        statement = select(Project).order_by(Project.created_at, Project.id)
        if status is not None:
            statement = statement.where(Project.status == status)
        statement = statement.offset(offset).limit(limit)
        return self.session.scalars(statement).all()

    def update(
        self,
        project: Project,
        *,
        project_code: str | None = None,
        name: str | None = None,
        normalized_name: str | None = None,
        status: ProjectStatus | None = None,
    ) -> Project:
        if project_code is not None:
            project.project_code = project_code
        if name is not None:
            project.name = name
        if normalized_name is not None:
            project.normalized_name = normalized_name
        if status is not None:
            project.status = status
        self.session.flush()
        return project
