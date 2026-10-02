from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, ProjectCandidateQuery
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_contact import ProjectContact
from app.repositories.project_contact import ProjectContactRepository
from app.services.project_candidate_retrieval import retrieve_contact_candidates


def _contact_match(code: str, *, active: bool = True):
    project = Project(
        id=uuid4(),
        project_code=code,
        name=f"Project {code}",
        normalized_name=f"project {code.casefold()}",
        status=ProjectStatus.ACTIVE,
    )
    contact = ProjectContact(
        id=uuid4(),
        project_id=project.id,
        email_normalized="person@example.com",
        display_name="Project Contact",
        is_active=active,
    )
    return contact, project


def test_retrieves_active_contact_project_with_exact_email_signal() -> None:
    repository = MagicMock(spec=ProjectContactRepository)
    repository.find_active_with_projects.return_value = [_contact_match("ONE")]
    query = ProjectCandidateQuery(
        source="fixture",
        sender_email_normalized=" Person@Example.COM ",
    )

    result = retrieve_contact_candidates(query, repository)

    repository.find_active_with_projects.assert_called_once_with("person@example.com")
    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.PROJECT_CONTACT
    assert signal.source is CandidateSignalSource.PROJECT_RECORD
    assert signal.matched_value == "person@example.com"
    assert signal.exact is True


def test_shared_contact_keeps_multiple_projects_ambiguous() -> None:
    repository = MagicMock(spec=ProjectContactRepository)
    repository.find_active_with_projects.return_value = [
        _contact_match("ONE"),
        _contact_match("TWO"),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        sender_email_normalized="person@example.com",
    )

    result = retrieve_contact_candidates(query, repository)

    assert result.cardinality is CandidateSetCardinality.MULTIPLE
    assert result.is_ambiguous is True


def test_missing_or_unknown_sender_returns_no_candidates() -> None:
    repository = MagicMock(spec=ProjectContactRepository)
    repository.find_active_with_projects.return_value = []

    missing = retrieve_contact_candidates(
        ProjectCandidateQuery(source="fixture"), repository
    )
    unknown = retrieve_contact_candidates(
        ProjectCandidateQuery(
            source="fixture", sender_email_normalized="unknown@example.com"
        ),
        repository,
    )

    assert missing.candidates == ()
    assert unknown.candidates == ()
    repository.find_active_with_projects.assert_called_once_with("unknown@example.com")


def test_defensively_ignores_inactive_and_duplicate_project_rows() -> None:
    repository = MagicMock(spec=ProjectContactRepository)
    active_contact, project = _contact_match("ONE")
    inactive_contact, _ = _contact_match("IGNORED", active=False)
    repository.find_active_with_projects.return_value = [
        (inactive_contact, project),
        (active_contact, project),
        (active_contact, project),
    ]
    query = ProjectCandidateQuery(
        source="fixture", sender_email_normalized="person@example.com"
    )

    result = retrieve_contact_candidates(query, repository)

    assert len(result.candidates) == 1
