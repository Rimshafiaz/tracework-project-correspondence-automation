from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import RequirementState
from app.models.requirement import Requirement


class RequirementRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        project_id: UUID,
        name: str,
        description: str | None = None,
        expected_date: date | None = None,
    ) -> Requirement:
        requirement = Requirement(
            project_id=project_id,
            name=name,
            description=description,
            state=RequirementState.OPEN,
            expected_date=expected_date,
        )
        self.session.add(requirement)
        self.session.flush()
        return requirement

    def get(self, requirement_id: UUID) -> Requirement | None:
        return self.session.get(Requirement, requirement_id)

    def list_for_project(self, project_id: UUID) -> Sequence[Requirement]:
        statement = (
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.created_at, Requirement.id)
        )
        return self.session.scalars(statement).all()

    def update_details(
        self,
        requirement: Requirement,
        *,
        name: str,
        description: str | None,
        expected_date: date | None,
    ) -> Requirement:
        requirement.name = name
        requirement.description = description
        requirement.expected_date = expected_date
        self.session.flush()
        return requirement
