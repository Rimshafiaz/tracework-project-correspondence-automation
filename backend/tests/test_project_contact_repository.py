from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_contact import ProjectContact
from app.repositories.project_contact import ProjectContactRepository


def test_create_adds_active_contact_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectContactRepository(session)
    project_id = uuid4()

    contact = repository.create(
        project_id=project_id,
        email_normalized="trusted@example.com",
        display_name="Trusted Contact",
        role=None,
    )

    assert contact.project_id == project_id
    assert contact.email_normalized == "trusted@example.com"
    assert contact.is_active is True
    session.add.assert_called_once_with(contact)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_list_for_project_is_ordered_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectContactRepository(session)
    expected = [MagicMock(spec=ProjectContact)]
    session.scalars.return_value.all.return_value = expected

    assert repository.list_for_project(uuid4()) == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 1
    assert len(statement._order_by_clauses) == 2
    session.commit.assert_not_called()


def test_get_contact_uses_primary_key_lookup() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectContactRepository(session)
    contact_id = uuid4()
    contact = MagicMock(spec=ProjectContact)
    session.get.return_value = contact

    assert repository.get(contact_id) is contact
    session.get.assert_called_once_with(ProjectContact, contact_id)


def test_find_active_with_projects_is_exact_ordered_and_read_only() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectContactRepository(session)
    contact = MagicMock(spec=ProjectContact)
    project = MagicMock(spec=Project)
    session.execute.return_value = [(contact, project)]

    result = repository.find_active_with_projects("person@example.com")

    assert result == [(contact, project)]
    statement = session.execute.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert len(statement._order_by_clauses) == 3
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_find_active_with_projects_skips_empty_input() -> None:
    session = MagicMock(spec=Session)
    repository = ProjectContactRepository(session)

    assert repository.find_active_with_projects("") == []
    session.execute.assert_not_called()
