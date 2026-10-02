from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_contact import ProjectContact


class ProjectContactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_active_with_projects(
        self,
        email_normalized: str,
    ) -> Sequence[tuple[ProjectContact, Project]]:
        if not email_normalized:
            return []
        statement = (
            select(ProjectContact, Project)
            .join(Project, Project.id == ProjectContact.project_id)
            .where(
                ProjectContact.email_normalized == email_normalized,
                ProjectContact.is_active.is_(True),
            )
            .order_by(Project.project_code, Project.id, ProjectContact.id)
        )
        return [tuple(row) for row in self.session.execute(statement)]
