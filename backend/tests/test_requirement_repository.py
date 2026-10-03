from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.enums import RequirementState
from app.models.requirement import Requirement
from app.repositories.requirement import RequirementRepository


def test_create_adds_and_flushes_open_requirement() -> None:
    session = MagicMock(spec=Session)
    repository = RequirementRepository(session)

    requirement = repository.create(project_id=uuid4(), name="Security review")

    assert requirement.name == "Security review"
    assert requirement.state is RequirementState.OPEN
    session.add.assert_called_once_with(requirement)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_get_and_list_use_scoped_queries() -> None:
    session = MagicMock(spec=Session)
    repository = RequirementRepository(session)
    requirement_id = uuid4()
    project_id = uuid4()
    expected = MagicMock(spec=Requirement)
    session.get.return_value = expected
    session.scalars.return_value.all.return_value = [expected]

    assert repository.get(requirement_id) is expected
    assert repository.list_for_project(project_id) == [expected]
    session.get.assert_called_once_with(Requirement, requirement_id)
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1


def test_locking_reads_use_for_update() -> None:
    session = MagicMock(spec=Session)
    repository = RequirementRepository(session)
    session.scalar.return_value = None
    session.scalars.return_value.all.return_value = []

    repository.get_for_update(uuid4())
    repository.list_for_project_for_update(uuid4())

    assert session.scalar.call_args.args[0]._for_update_arg is not None
    assert session.scalars.call_args.args[0]._for_update_arg is not None


def test_apply_authorized_change_updates_state_without_commit() -> None:
    session = MagicMock(spec=Session)
    repository = RequirementRepository(session)
    requirement = Requirement(
        project_id=uuid4(),
        name="Neutral requirement",
        state=RequirementState.OPEN,
    )

    repository.apply_authorized_change(
        requirement,
        state=RequirementState.PARTIAL,
        expected_date=None,
    )

    assert requirement.state is RequirementState.PARTIAL
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_update_details_does_not_change_state_or_commit() -> None:
    session = MagicMock(spec=Session)
    repository = RequirementRepository(session)
    requirement = Requirement(
        project_id=uuid4(),
        name="Old name",
        state=RequirementState.PARTIAL,
    )

    result = repository.update_details(
        requirement,
        name="New name",
        description=None,
        expected_date=date(2027, 1, 15),
    )

    assert result is requirement
    assert requirement.name == "New name"
    assert requirement.expected_date == date(2027, 1, 15)
    assert requirement.state is RequirementState.PARTIAL
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()
