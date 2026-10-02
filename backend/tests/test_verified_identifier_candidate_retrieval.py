from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateIdentifierHint, CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, ProjectCandidateQuery
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_identifier import ProjectIdentifier
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import retrieve_verified_identifier_candidates


def _match(
    *, identifier_type: str, normalized_value: str, project: Project
) -> tuple[ProjectIdentifier, Project]:
    return (
        ProjectIdentifier(
            id=uuid4(),
            project_id=project.id,
            identifier_type=identifier_type,
            display_value=normalized_value,
            normalized_value=normalized_value,
            verified=True,
        ),
        project,
    )


def test_retrieves_verified_identifier_with_generic_type_and_provenance() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    project = Project(
        id=uuid4(),
        project_code="PLATFORM",
        name="Platform Modernization",
        normalized_name="platform modernization",
        status=ProjectStatus.ACTIVE,
    )
    repository.find_verified_exact_with_projects.return_value = [
        _match(
            identifier_type="repository",
            normalized_value="example/platform",
            project=project,
        )
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type=" Repository ",
                normalized_value=" Example/Platform ",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_verified_identifier_candidates(query, repository)

    repository.find_verified_exact_with_projects.assert_called_once_with(
        {("repository", "example/platform")}
    )
    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.VERIFIED_IDENTIFIER
    assert signal.identifier_type == "repository"
    assert signal.evidence_item_id is None
    assert signal.verified is True


def test_combines_multiple_identifier_matches_for_the_same_project() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    project = Project(
        id=uuid4(),
        project_code="GENERIC",
        name="Generic Project",
        normalized_name="generic project",
        status=ProjectStatus.ACTIVE,
    )
    repository.find_verified_exact_with_projects.return_value = [
        _match(identifier_type="repository", normalized_value="org/repo", project=project),
        _match(identifier_type="client_ref", normalized_value="ref-1", project=project),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="repository",
                normalized_value="org/repo",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
            CandidateIdentifierHint(
                identifier_type="client_ref",
                normalized_value="ref-1",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_verified_identifier_candidates(query, repository)

    assert result.cardinality is CandidateSetCardinality.SINGLE
    assert len(result.candidates[0].signals) == 2


def test_multiple_projects_remain_ambiguous_and_unmatched_input_stays_empty() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    first = Project(
        id=uuid4(), project_code="ONE", name="One", normalized_name="one", status=ProjectStatus.ACTIVE
    )
    second = Project(
        id=uuid4(), project_code="TWO", name="Two", normalized_name="two", status=ProjectStatus.ACTIVE
    )
    repository.find_verified_exact_with_projects.return_value = [
        _match(identifier_type="domain", normalized_value="example.com", project=first),
        _match(identifier_type="domain", normalized_value="example.com", project=second),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="domain",
                normalized_value="example.com",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    ambiguous = retrieve_verified_identifier_candidates(query, repository)
    repository.find_verified_exact_with_projects.return_value = []
    unmatched = retrieve_verified_identifier_candidates(query, repository)

    assert ambiguous.cardinality is CandidateSetCardinality.MULTIPLE
    assert ambiguous.is_ambiguous is True
    assert unmatched.candidates == ()


def test_never_promotes_an_unverified_identifier_to_a_strong_match() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    project = Project(
        id=uuid4(),
        project_code="ONE",
        name="One",
        normalized_name="one",
        status=ProjectStatus.ACTIVE,
    )
    identifier, _ = _match(
        identifier_type="external_id",
        normalized_value="external-1",
        project=project,
    )
    identifier.verified = False
    repository.find_verified_exact_with_projects.return_value = [(identifier, project)]
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="external_id",
                normalized_value="external-1",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_verified_identifier_candidates(query, repository)

    assert result.candidates == ()
