from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.models.requirement import Requirement
from app.repositories.requirement import RequirementRepository


class _Unset:
    pass


UNSET = _Unset()


class RequirementService:
    def __init__(self, repository: RequirementRepository) -> None:
        self.repository = repository

    def create(
        self,
        *,
        project_id: UUID,
        name: str,
        description: str | None = None,
        expected_date: date | None = None,
    ) -> Requirement:
        return self.repository.create(
            project_id=project_id,
            name=name,
            description=description,
            expected_date=expected_date,
        )

    def get(self, requirement_id: UUID) -> Requirement | None:
        return self.repository.get(requirement_id)

    def list_for_project(self, project_id: UUID) -> Sequence[Requirement]:
        return self.repository.list_for_project(project_id)

    def update_details(
        self,
        requirement_id: UUID,
        *,
        name: str | _Unset = UNSET,
        description: str | None | _Unset = UNSET,
        expected_date: date | None | _Unset = UNSET,
    ) -> Requirement:
        requirement = self.repository.get(requirement_id)
        if requirement is None:
            raise LookupError(f"Requirement {requirement_id} was not found")
        return self.repository.update_details(
            requirement,
            name=requirement.name if isinstance(name, _Unset) else name,
            description=(
                requirement.description
                if isinstance(description, _Unset)
                else description
            ),
            expected_date=(
                requirement.expected_date
                if isinstance(expected_date, _Unset)
                else expected_date
            ),
        )
