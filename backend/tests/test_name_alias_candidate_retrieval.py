from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, CandidateValueHint, ProjectCandidateQuery
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_identifier import ProjectIdentifier
from app.repositories.project import ProjectRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import retrieve_name_and_alias_candidates


def _project(code: str, name: str) -> Project:
    return Project(
        id=uuid4(),
        project_code=code,
        name=name,
        normalized_name=name.casefold(),
        status=ProjectStatus.ACTIVE,
    )


def _alias(project: Project, value: str, *, verified: bool = True):
    return (
        ProjectIdentifier(
            id=uuid4(),
            project_id=project.id,
            identifier_type="alias",
            display_value=value,
            normalized_value=value.casefold(),
            verified=verified,
        ),
        project,
    )


def test_retrieves_exact_normalized_name_with_provenance() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    project = _project("PORTAL", "Customer Portal")
    project_repository.find_by_normalized_names.return_value = [project]
    identifier_repository.find_verified_exact_with_projects.return_value = []
    evidence_id = uuid4()
    query = ProjectCandidateQuery(
        source="fixture",
        normalized_names=(
            CandidateValueHint(
                normalized_value="  Customer\tPortal ",
                source=CandidateSignalSource.EVIDENCE_ITEM,
                evidence_item_id=evidence_id,
            ),
        ),
    )

    result = retrieve_name_and_alias_candidates(
        query, project_repository, identifier_repository
    )

    project_repository.find_by_normalized_names.assert_called_once_with(
        {"customer portal"}
    )
    identifier_repository.find_verified_exact_with_projects.assert_called_once_with(
        {("alias", "customer portal")}
    )
    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.NORMALIZED_NAME
    assert signal.evidence_item_id == evidence_id


def test_retrieves_verified_alias_and_combines_it_with_name_match() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    project = _project("PORTAL", "Customer Portal")
    project_repository.find_by_normalized_names.return_value = [project]
    alias_match = _alias(project, "Customer Portal")
    identifier_repository.find_verified_exact_with_projects.return_value = [alias_match]
    query = ProjectCandidateQuery(
        source="fixture",
        normalized_names=(
            CandidateValueHint(
                normalized_value="customer portal",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_name_and_alias_candidates(
        query, project_repository, identifier_repository
    )

    assert result.cardinality is CandidateSetCardinality.SINGLE
    assert [signal.signal_type for signal in result.candidates[0].signals] == [
        CandidateSignalType.NORMALIZED_NAME,
        CandidateSignalType.ALIAS,
    ]
    assert result.candidates[0].signals[1].verified is True
    assert result.candidates[0].signals[1].source_record_id == alias_match[0].id


def test_alias_only_matches_can_remain_ambiguous() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    first = _project("ONE", "First Project")
    second = _project("TWO", "Second Project")
    project_repository.find_by_normalized_names.return_value = []
    identifier_repository.find_verified_exact_with_projects.return_value = [
        _alias(first, "Shared Alias"),
        _alias(second, "Shared Alias"),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        normalized_names=(
            CandidateValueHint(
                normalized_value="shared alias",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_name_and_alias_candidates(
        query, project_repository, identifier_repository
    )

    assert result.cardinality is CandidateSetCardinality.MULTIPLE
    assert result.is_ambiguous is True


def test_unverified_or_non_alias_identifiers_are_not_alias_matches() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    project = _project("ONE", "First Project")
    unverified, _ = _alias(project, "Shared Alias", verified=False)
    wrong_type, _ = _alias(project, "Shared Alias")
    wrong_type.identifier_type = "domain"
    project_repository.find_by_normalized_names.return_value = []
    identifier_repository.find_verified_exact_with_projects.return_value = [
        (unverified, project),
        (wrong_type, project),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        normalized_names=(
            CandidateValueHint(
                normalized_value="shared alias",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_name_and_alias_candidates(
        query, project_repository, identifier_repository
    )

    assert result.candidates == ()
