from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, ProjectCandidateQuery
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.services.project_candidate_retrieval import retrieve_conversation_candidates


def _project(code: str) -> Project:
    return Project(
        id=uuid4(),
        project_code=code,
        name=f"Project {code}",
        normalized_name=f"project {code.casefold()}",
        status=ProjectStatus.ACTIVE,
    )


def test_retrieves_previously_approved_conversation_project() -> None:
    repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    project = _project("ONE")
    repository.find_approved_projects_for_conversation.return_value = [project]
    query = ProjectCandidateQuery(
        source=" Gmail ",
        external_conversation_id=" thread-1 ",
    )

    result = retrieve_conversation_candidates(query, repository)

    repository.find_approved_projects_for_conversation.assert_called_once_with(
        source="gmail",
        external_conversation_id="thread-1",
    )
    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.APPROVED_CONVERSATION
    assert signal.source is CandidateSignalSource.APPROVED_CONVERSATION_LINK
    assert signal.matched_value == "thread-1"
    assert signal.previously_approved is True


def test_conflicting_conversation_links_remain_ambiguous() -> None:
    repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    repository.find_approved_projects_for_conversation.return_value = [
        _project("ONE"),
        _project("TWO"),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        external_conversation_id="conversation-1",
    )

    result = retrieve_conversation_candidates(query, repository)

    assert result.cardinality is CandidateSetCardinality.MULTIPLE
    assert result.is_ambiguous is True


def test_missing_or_unknown_conversation_returns_no_candidates() -> None:
    repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    repository.find_approved_projects_for_conversation.return_value = []

    missing = retrieve_conversation_candidates(
        ProjectCandidateQuery(source="fixture"), repository
    )
    unknown = retrieve_conversation_candidates(
        ProjectCandidateQuery(
            source="fixture",
            external_conversation_id="unknown",
        ),
        repository,
    )

    assert missing.candidates == ()
    assert unknown.candidates == ()
    repository.find_approved_projects_for_conversation.assert_called_once()


def test_duplicate_project_rows_are_collapsed() -> None:
    repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    project = _project("ONE")
    repository.find_approved_projects_for_conversation.return_value = [project, project]
    query = ProjectCandidateQuery(
        source="fixture",
        external_conversation_id="conversation-1",
    )

    result = retrieve_conversation_candidates(query, repository)

    assert len(result.candidates) == 1
