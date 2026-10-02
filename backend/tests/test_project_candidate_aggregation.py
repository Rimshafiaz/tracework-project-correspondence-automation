from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.project_candidate import CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, CandidateValueHint, ProjectCandidate, ProjectCandidateQuery, ProjectCandidateSet, ProjectCandidateSignal
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_contact import ProjectContact
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import ProjectCandidateConflict, merge_project_candidate_sets, retrieve_project_candidates


def _candidate(
    project_id,
    code: str,
    signal_type: CandidateSignalType,
    *,
    name: str | None = None,
) -> ProjectCandidate:
    return ProjectCandidate(
        project_id=project_id,
        project_code=code,
        project_name=name or f"Project {code}",
        project_status=ProjectStatus.ACTIVE,
        signals=(
            ProjectCandidateSignal(
                signal_type=signal_type,
                matched_value=code.casefold(),
                source=CandidateSignalSource.PROJECT_RECORD,
                exact=True,
                previously_approved=(
                    signal_type is CandidateSignalType.APPROVED_CONVERSATION
                ),
            ),
        ),
    )


def test_merges_same_project_signals_and_removes_exact_duplicates() -> None:
    project_id = uuid4()
    code = _candidate(project_id, "ONE", CandidateSignalType.PROJECT_CODE)
    contact = _candidate(project_id, "ONE", CandidateSignalType.PROJECT_CONTACT)

    result = merge_project_candidate_sets(
        ProjectCandidateSet(candidates=(code,)),
        ProjectCandidateSet(candidates=(contact,)),
        ProjectCandidateSet(candidates=(code,)),
    )

    assert result.cardinality is CandidateSetCardinality.SINGLE
    assert [signal.signal_type for signal in result.candidates[0].signals] == [
        CandidateSignalType.PROJECT_CODE,
        CandidateSignalType.PROJECT_CONTACT,
    ]


def test_orders_projects_deterministically_and_preserves_ambiguity() -> None:
    first = _candidate(uuid4(), "BETA", CandidateSignalType.PROJECT_CODE)
    second = _candidate(uuid4(), "ALPHA", CandidateSignalType.NORMALIZED_NAME)

    result = merge_project_candidate_sets(
        ProjectCandidateSet(candidates=(first, second,))
    )

    assert [candidate.project_code for candidate in result.candidates] == [
        "ALPHA",
        "BETA",
    ]
    assert result.cardinality is CandidateSetCardinality.MULTIPLE
    assert result.is_ambiguous is True


def test_rejects_conflicting_identity_for_the_same_project_id() -> None:
    project_id = uuid4()
    first = _candidate(project_id, "ONE", CandidateSignalType.PROJECT_CODE)
    conflicting = _candidate(
        project_id,
        "ONE",
        CandidateSignalType.PROJECT_CONTACT,
        name="Different Name",
    )

    with pytest.raises(ProjectCandidateConflict, match="Conflicting identity"):
        merge_project_candidate_sets(
            ProjectCandidateSet(candidates=(first,)),
            ProjectCandidateSet(candidates=(conflicting,)),
        )


def test_orchestrator_runs_paths_and_combines_code_and_contact_evidence() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    contact_repository = MagicMock(spec=ProjectContactRepository)
    conversation_repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    project = Project(
        id=uuid4(),
        project_code="ONE",
        name="Project One",
        normalized_name="project one",
        status=ProjectStatus.ACTIVE,
    )
    contact = ProjectContact(
        id=uuid4(),
        project_id=project.id,
        email_normalized="person@example.com",
        display_name="Person",
        is_active=True,
    )
    project_repository.find_by_normalized_codes.return_value = [project]
    project_repository.find_by_normalized_names.return_value = []
    identifier_repository.find_verified_exact_with_projects.return_value = []
    contact_repository.find_active_with_projects.return_value = [(contact, project)]
    conversation_repository.find_approved_links_with_projects_for_conversation.return_value = []
    query = ProjectCandidateQuery(
        source="fixture",
        sender_email_normalized="person@example.com",
        project_codes=(
            CandidateValueHint(
                normalized_value="ONE",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
    )

    result = retrieve_project_candidates(
        query,
        project_repository=project_repository,
        identifier_repository=identifier_repository,
        contact_repository=contact_repository,
        conversation_repository=conversation_repository,
    )

    assert len(result.candidates) == 1
    assert [signal.signal_type for signal in result.candidates[0].signals] == [
        CandidateSignalType.PROJECT_CODE,
        CandidateSignalType.PROJECT_CONTACT,
    ]
    assert identifier_repository.find_verified_exact_with_projects.call_count == 3
    project_repository.list_for_fuzzy_name_retrieval.assert_not_called()
