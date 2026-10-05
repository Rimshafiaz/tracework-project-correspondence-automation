from types import SimpleNamespace
from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts.project_setup import ProjectSetupRequest
from app.core.auth import AuthenticatedOperator
from app.models.enums import ProjectStatus, RequirementState
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.services.project_setup import (
    ProjectSetupService,
)


def _request() -> ProjectSetupRequest:
    return ProjectSetupRequest.model_validate(
        {
            "name": "Neutral Project",
            "identifiers": [
                {"identifier_type": "External Reference", "display_value": "Ref 10"}
            ],
            "contacts": [
                {
                    "email": "TRUSTED@EXAMPLE.COM",
                    "display_name": "Trusted Contact",
                    "role": "Reviewer",
                }
            ],
            "requirements": [
                {"name": "Initial approval", "expected_date": "2026-10-20"}
            ],
        }
    )


def _service():
    session = MagicMock(spec=Session)
    projects = MagicMock(spec=ProjectRepository)
    identifiers = MagicMock(spec=ProjectIdentifierRepository)
    contacts = MagicMock(spec=ProjectContactRepository)
    requirements = MagicMock(spec=RequirementRepository)
    audit = MagicMock(spec=LineageRepository)
    for repository in (projects, identifiers, contacts, requirements, audit):
        repository.session = session

    project = SimpleNamespace(
        id=uuid4(),
        project_code="TW-001",
        name="Neutral Project",
        status=ProjectStatus.ACTIVE,
    )
    identifier = SimpleNamespace(
        id=uuid4(),
        identifier_type="external reference",
        display_value="Ref 10",
        verified=True,
    )
    contact = SimpleNamespace(
        id=uuid4(),
        email_normalized="trusted@example.com",
        display_name="Trusted Contact",
        role="Reviewer",
        is_active=True,
    )
    requirement = SimpleNamespace(
        id=uuid4(),
        name="Initial approval",
        state=RequirementState.OPEN,
        expected_date=_request().requirements[0].expected_date,
    )
    projects.find_by_normalized_codes.return_value = []
    projects.allocate_project_code.return_value = "TW-001"
    projects.create.return_value = project
    identifiers.create.return_value = identifier
    contacts.create.return_value = contact
    requirements.create.return_value = requirement
    return (
        ProjectSetupService(
            session=session,
            project_repository=projects,
            identifier_repository=identifiers,
            contact_repository=contacts,
            requirement_repository=requirements,
            audit_repository=audit,
        ),
        session,
        projects,
        identifiers,
        contacts,
        requirements,
        audit,
        project,
    )


def test_setup_creates_authoritative_baseline_and_audits_operator() -> None:
    service, session, projects, identifiers, contacts, requirements, audit, project = _service()
    operator = AuthenticatedOperator(subject="supabase-user-1")

    result = service.create(_request(), operator=operator)

    assert result.project_id == project.id
    projects.allocate_project_code.assert_called_once_with()
    projects.create.assert_called_once_with(
        project_code="TW-001",
        name="Neutral Project",
        normalized_name="neutral project",
    )
    identifiers.create.assert_called_once_with(
        project_id=project.id,
        identifier_type="external reference",
        display_value="Ref 10",
        normalized_value="ref 10",
        verified=True,
    )
    contacts.create.assert_called_once_with(
        project_id=project.id,
        email_normalized="trusted@example.com",
        display_name="Trusted Contact",
        role="Reviewer",
    )
    requirements.create.assert_called_once_with(
        project_id=project.id,
        name="Initial approval",
        description=None,
        expected_date=_request().requirements[0].expected_date,
    )
    assert audit.create_audit_event.call_count == 4
    assert all(
        item.kwargs["actor_type"] == "authenticated_operator"
        and item.kwargs["actor_identifier"] == "supabase-user-1"
        for item in audit.create_audit_event.call_args_list
    )
    assert audit.create_audit_event.call_args_list[-1].kwargs["details"]["state"] == "OPEN"
    assert audit.create_audit_event.call_args_list[0].kwargs["details"]["project_code"] == "TW-001"
    audit.create_proposal.assert_not_called()
    audit.create_policy_evaluation.assert_not_called()
    audit.create_transition.assert_not_called()
    audit.create_evidence.assert_not_called()
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()


def test_sequence_values_above_999_are_not_truncated() -> None:
    service, _, projects, _, _, _, _, project = _service()
    projects.allocate_project_code.return_value = "TW-1000"
    project.project_code = "TW-1000"

    service.create(_request(), operator=AuthenticatedOperator(subject="operator"))

    assert projects.create.call_args.kwargs["project_code"] == "TW-1000"


def test_failed_setup_may_consume_code_but_rolls_back_project() -> None:
    service, session, projects, identifiers, _, _, _, _ = _service()
    identifiers.create.side_effect = RuntimeError("injected setup failure")

    with pytest.raises(RuntimeError, match="injected setup failure"):
        service.create(_request(), operator=AuthenticatedOperator(subject="operator"))

    projects.allocate_project_code.assert_called_once_with()
    projects.create.assert_called_once()
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize("failure_target", ["identifier", "contact", "requirement", "audit"])
def test_child_or_audit_failure_rolls_back_complete_setup(failure_target: str) -> None:
    service, session, projects, identifiers, contacts, requirements, audit, _ = _service()
    error = RuntimeError("injected setup failure")
    {
        "identifier": identifiers.create,
        "contact": contacts.create,
        "requirement": requirements.create,
        "audit": audit.create_audit_event,
    }[failure_target].side_effect = error

    with pytest.raises(RuntimeError, match="injected setup failure"):
        service.create(_request(), operator=AuthenticatedOperator(subject="operator"))

    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()
    projects.allocate_project_code.assert_called_once_with()
