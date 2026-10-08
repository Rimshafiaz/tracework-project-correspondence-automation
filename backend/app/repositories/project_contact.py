from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_contact import ProjectContact


class ProjectContactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, contact_id: UUID) -> ProjectContact | None:
        return self.session.get(ProjectContact, contact_id)

    def create(
        self,
        *,
        project_id: UUID,
        email_normalized: str,
        display_name: str,
        role: str | None = None,
    ) -> ProjectContact:
        contact = ProjectContact(
            project_id=project_id,
            email_normalized=email_normalized,
            display_name=display_name,
            role=role,
            is_active=True,
        )
        self.session.add(contact)
        self.session.flush()
        return contact

    def list_for_project(self, project_id: UUID) -> Sequence[ProjectContact]:
        statement = (
            select(ProjectContact)
            .where(ProjectContact.project_id == project_id)
            .order_by(ProjectContact.created_at, ProjectContact.id)
        )
        return self.session.scalars(statement).all()

    def get_active_for_project_email(
        self,
        *,
        project_id: UUID,
        email_normalized: str,
    ) -> ProjectContact | None:
        if not email_normalized:
            return None
        return self.session.scalar(
            select(ProjectContact).where(
                ProjectContact.project_id == project_id,
                ProjectContact.email_normalized == email_normalized,
                ProjectContact.is_active.is_(True),
            )
        )

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
