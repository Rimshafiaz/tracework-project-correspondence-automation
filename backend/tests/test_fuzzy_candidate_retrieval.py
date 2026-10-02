from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, CandidateValueHint, FuzzyCandidateOptions, ProjectCandidateQuery, ProjectCandidateSet
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_identifier import ProjectIdentifier
from app.repositories.project import ProjectRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import retrieve_fuzzy_name_alias_candidates


def _project(code: str, name: str) -> Project:
    return Project(
        id=uuid4(),
        project_code=code,
        name=name,
        normalized_name=name.casefold(),
        status=ProjectStatus.ACTIVE,
    )


def _query(name: str) -> ProjectCandidateQuery:
    return ProjectCandidateQuery(
        source="fixture",
        normalized_names=(
            CandidateValueHint(
                normalized_value=name,
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )


def test_fuzzy_name_match_is_labeled_scored_and_not_exact() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    project_repository.list_for_fuzzy_name_retrieval.return_value = [
        _project("PORTAL", "Customer Portal Modernization")
    ]
    identifier_repository.list_verified_type_with_projects.return_value = []

    result = retrieve_fuzzy_name_alias_candidates(
        _query("Customer Portal Modernisation"),
        project_repository,
        identifier_repository,
        FuzzyCandidateOptions(minimum_score=70, max_candidates_per_hint=3),
    )

    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.FUZZY_NAME
    assert signal.exact is False
    assert 70 <= signal.similarity_score < 100
    assert "selected_project_id" not in ProjectCandidateSet.model_fields


def test_fuzzy_verified_alias_preserves_alias_semantics() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    project = _project("PLATFORM", "Platform Replacement")
    alias = ProjectIdentifier(
        id=uuid4(),
        project_id=project.id,
        identifier_type="alias",
        display_value="Portal Upgrade",
        normalized_value="portal upgrade",
        verified=True,
    )
    project_repository.list_for_fuzzy_name_retrieval.return_value = []
    identifier_repository.list_verified_type_with_projects.return_value = [
        (alias, project)
    ]

    result = retrieve_fuzzy_name_alias_candidates(
        _query("Portal Upgade"),
        project_repository,
        identifier_repository,
        FuzzyCandidateOptions(minimum_score=70, max_candidates_per_hint=3),
    )

    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.FUZZY_ALIAS
    assert signal.identifier_type == "alias"
    assert signal.source_record_id == alias.id
    assert signal.verified is True


def test_fuzzy_retrieval_is_bounded_and_excludes_exact_matches() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    exact = _project("EXACT", "Customer Portal")
    near = _project("NEAR", "Customer Portals")
    other = _project("OTHER", "Customer Portal Legacy")
    project_repository.list_for_fuzzy_name_retrieval.return_value = [exact, near, other]
    identifier_repository.list_verified_type_with_projects.return_value = []

    result = retrieve_fuzzy_name_alias_candidates(
        _query("Customer Portal"),
        project_repository,
        identifier_repository,
        FuzzyCandidateOptions(minimum_score=60, max_candidates_per_hint=1),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].project_id != exact.id


def test_fuzzy_retrieval_does_not_scan_without_name_hints() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)

    result = retrieve_fuzzy_name_alias_candidates(
        ProjectCandidateQuery(source="fixture"),
        project_repository,
        identifier_repository,
        FuzzyCandidateOptions(minimum_score=70, max_candidates_per_hint=3),
    )

    assert result.candidates == ()
    project_repository.list_for_fuzzy_name_retrieval.assert_not_called()
    identifier_repository.list_verified_type_with_projects.assert_not_called()
