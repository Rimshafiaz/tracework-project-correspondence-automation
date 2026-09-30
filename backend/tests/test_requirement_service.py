from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.requirement import Requirement
from app.repositories.requirement import RequirementRepository
from app.services.requirement import RequirementService


def test_update_details_loads_then_updates_requirement() -> None:
    repository = MagicMock(spec=RequirementRepository)
    service = RequirementService(repository)
    requirement_id = uuid4()
    requirement = MagicMock(spec=Requirement)
    requirement.description = "Existing description"
    repository.get.return_value = requirement
    repository.update_details.return_value = requirement
    expected_date = date(2027, 1, 15)

    result = service.update_details(
        requirement_id,
        name="Updated requirement",
        expected_date=expected_date,
    )

    assert result is requirement
    repository.get.assert_called_once_with(requirement_id)
    repository.update_details.assert_called_once_with(
        requirement,
        name="Updated requirement",
        description="Existing description",
        expected_date=expected_date,
    )


def test_update_details_can_clear_nullable_fields() -> None:
    repository = MagicMock(spec=RequirementRepository)
    service = RequirementService(repository)
    requirement = MagicMock(spec=Requirement)
    requirement.name = "Requirement"
    requirement.description = "Existing description"
    requirement.expected_date = date(2027, 1, 15)
    repository.get.return_value = requirement
    repository.update_details.return_value = requirement

    service.update_details(uuid4(), description=None, expected_date=None)

    repository.update_details.assert_called_once_with(
        requirement,
        name="Requirement",
        description=None,
        expected_date=None,
    )


def test_update_details_rejects_unknown_requirement() -> None:
    repository = MagicMock(spec=RequirementRepository)
    service = RequirementService(repository)
    requirement_id = uuid4()
    repository.get.return_value = None

    with pytest.raises(LookupError, match=str(requirement_id)):
        service.update_details(requirement_id, name="Updated requirement")

    repository.update_details.assert_not_called()
