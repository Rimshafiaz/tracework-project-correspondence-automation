from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateSetCardinality, CandidateSignalSource, CandidateValueHint, ProjectCandidateQuery
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.repositories.project import ProjectRepository
from app.services.project_candidate_retrieval import retrieve_project_code_candidates


def test_retrieves_exact_code_and_preserves_hint_provenance() -> None:
    repository = MagicMock(spec=ProjectRepository)
    project = Project(
        id=uuid4(),
        project_code="PROJ-42",
        name="Platform Upgrade",
        normalized_name="platform upgrade",
        status=ProjectStatus.ACTIVE,
    )
    repository.find_by_normalized_codes.return_value = [project]
    attachment_id = uuid4()
    query = ProjectCandidateQuery(
        source="fixture",
        project_codes=(
            CandidateValueHint(
                normalized_value="  PROJ-42  ",
                source=CandidateSignalSource.ATTACHMENT,
                attachment_id=attachment_id,
            ),
        ),
    )

    result = retrieve_project_code_candidates(query, repository)

    repository.find_by_normalized_codes.assert_called_once_with({"proj-42"})
    assert result.cardinality is CandidateSetCardinality.SINGLE
    assert result.candidates[0].project_id == project.id
    assert result.candidates[0].signals[0].matched_value == "proj-42"
    assert result.candidates[0].signals[0].attachment_id == attachment_id


def test_deduplicates_identical_hints_but_preserves_distinct_sources() -> None:
    repository = MagicMock(spec=ProjectRepository)
    project = Project(
        id=uuid4(),
        project_code="ALPHA",
        name="Alpha",
        normalized_name="alpha",
        status=ProjectStatus.CLOSED,
    )
    repository.find_by_normalized_codes.return_value = [project]
    repeated = CandidateValueHint(
        normalized_value="alpha",
        source=CandidateSignalSource.CORRESPONDENCE_EVENT,
    )
    query = ProjectCandidateQuery(
        source="fixture",
        project_codes=(
            repeated,
            repeated,
            CandidateValueHint(
                normalized_value="ALPHA",
                source=CandidateSignalSource.EVIDENCE_ITEM,
                evidence_item_id=uuid4(),
            ),
        ),
    )

    result = retrieve_project_code_candidates(query, repository)

    assert len(result.candidates[0].signals) == 2
    assert result.candidates[0].project_status is ProjectStatus.CLOSED


def test_empty_or_unmatched_codes_return_no_candidates() -> None:
    repository = MagicMock(spec=ProjectRepository)
    repository.find_by_normalized_codes.return_value = []

    empty = retrieve_project_code_candidates(
        ProjectCandidateQuery(source="fixture"), repository
    )
    unmatched = retrieve_project_code_candidates(
        ProjectCandidateQuery(
            source="fixture",
            project_codes=(
                CandidateValueHint(
                    normalized_value="missing",
                    source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                ),
            ),
        ),
        repository,
    )

    assert empty.candidates == ()
    assert unmatched.candidates == ()
    assert repository.find_by_normalized_codes.call_args_list[0].args == (set(),)
