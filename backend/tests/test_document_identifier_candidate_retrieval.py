from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.project_candidate import CandidateIdentifierHint, CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, ProjectCandidateQuery
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_identifier import ProjectIdentifier
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import retrieve_document_identifier_candidates


def _project(code: str) -> Project:
    return Project(
        id=uuid4(),
        project_code=code,
        name=f"Project {code}",
        normalized_name=f"project {code.casefold()}",
        status=ProjectStatus.ACTIVE,
    )


def _match(project: Project, identifier_type: str, value: str, *, verified: bool = True):
    return (
        ProjectIdentifier(
            id=uuid4(),
            project_id=project.id,
            identifier_type=identifier_type,
            display_value=value,
            normalized_value=value.casefold(),
            verified=verified,
        ),
        project,
    )


def test_retrieves_document_identifier_with_attachment_and_evidence_provenance() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    project = _project("PORTAL")
    repository.find_verified_exact_with_projects.return_value = [
        _match(project, "repository", "example/portal")
    ]
    attachment_id = uuid4()
    evidence_id = uuid4()
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="Repository",
                normalized_value="Example/Portal",
                source=CandidateSignalSource.EVIDENCE_ITEM,
                attachment_id=attachment_id,
                evidence_item_id=evidence_id,
            ),
        ),
    )

    result = retrieve_document_identifier_candidates(query, repository)

    repository.find_verified_exact_with_projects.assert_called_once_with(
        {("repository", "example/portal")}
    )
    signal = result.candidates[0].signals[0]
    assert signal.signal_type is CandidateSignalType.DOCUMENT_IDENTIFIER
    assert signal.attachment_id == attachment_id
    assert signal.evidence_item_id == evidence_id
    assert signal.verified is True


def test_combines_document_identifiers_and_preserves_cross_project_ambiguity() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    first = _project("ONE")
    second = _project("TWO")
    repository.find_verified_exact_with_projects.return_value = [
        _match(first, "client_ref", "ref-1"),
        _match(first, "repository", "org/repo"),
        _match(second, "client_ref", "ref-1"),
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="client_ref",
                normalized_value="ref-1",
                source=CandidateSignalSource.ATTACHMENT,
                attachment_id=uuid4(),
            ),
            CandidateIdentifierHint(
                identifier_type="repository",
                normalized_value="org/repo",
                source=CandidateSignalSource.EVIDENCE_ITEM,
                evidence_item_id=uuid4(),
            ),
        ),
    )

    result = retrieve_document_identifier_candidates(query, repository)

    assert result.cardinality is CandidateSetCardinality.MULTIPLE
    assert len(result.candidates[0].signals) == 2
    assert result.is_ambiguous is True


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (CandidateSignalSource.ATTACHMENT, "attachment_id"),
        (CandidateSignalSource.EVIDENCE_ITEM, "evidence_item_id"),
    ],
)
def test_document_hints_require_source_provenance(
    source: CandidateSignalSource,
    error: str,
) -> None:
    with pytest.raises(ValidationError, match=error):
        CandidateIdentifierHint(
            identifier_type="external_id",
            normalized_value="external-1",
            source=source,
        )


def test_ignores_non_document_hints_and_unverified_matches() -> None:
    repository = MagicMock(spec=ProjectIdentifierRepository)
    project = _project("ONE")
    unverified = _match(project, "external_id", "external-1", verified=False)
    repository.find_verified_exact_with_projects.return_value = [unverified]
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

    result = retrieve_document_identifier_candidates(query, repository)

    repository.find_verified_exact_with_projects.assert_called_once_with(set())
    assert result.candidates == ()
