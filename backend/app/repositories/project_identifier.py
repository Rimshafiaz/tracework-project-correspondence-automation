from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_identifier import ProjectIdentifier


class ProjectIdentifierRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        project_id: UUID,
        identifier_type: str,
        display_value: str,
        normalized_value: str,
        verified: bool = False,
    ) -> ProjectIdentifier:
        identifier = ProjectIdentifier(
            project_id=project_id,
            identifier_type=identifier_type,
            display_value=display_value,
            normalized_value=normalized_value,
            verified=verified,
        )
        self.session.add(identifier)
        self.session.flush()
        return identifier

    def get(self, identifier_id: UUID) -> ProjectIdentifier | None:
        return self.session.get(ProjectIdentifier, identifier_id)

    def list_for_project(self, project_id: UUID) -> Sequence[ProjectIdentifier]:
        statement = (
            select(ProjectIdentifier)
            .where(ProjectIdentifier.project_id == project_id)
            .order_by(ProjectIdentifier.created_at, ProjectIdentifier.id)
        )
        return self.session.scalars(statement).all()

    def find_exact(
        self,
        *,
        identifier_type: str,
        normalized_value: str,
        verified_only: bool = True,
    ) -> Sequence[ProjectIdentifier]:
        statement = select(ProjectIdentifier).where(
            ProjectIdentifier.identifier_type == identifier_type,
            ProjectIdentifier.normalized_value == normalized_value,
        )
        if verified_only:
            statement = statement.where(ProjectIdentifier.verified.is_(True))
        return self.session.scalars(statement).all()

    def update(
        self,
        identifier: ProjectIdentifier,
        *,
        display_value: str | None = None,
        normalized_value: str | None = None,
        verified: bool | None = None,
    ) -> ProjectIdentifier:
        if display_value is not None:
            identifier.display_value = display_value
        if normalized_value is not None:
            identifier.normalized_value = normalized_value
        if verified is not None:
            identifier.verified = verified
        self.session.flush()
        return identifier
