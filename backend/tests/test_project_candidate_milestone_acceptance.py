from unittest.mock import MagicMock
from uuid import uuid4

from app.contracts.project_candidate import CandidateIdentifierHint, CandidateSetCardinality, CandidateSignalSource, CandidateSignalType, CandidateValueHint, ProjectCandidateQuery, ProjectCandidateSet
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_contact import ProjectContact
from app.models.project_identifier import ProjectIdentifier
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import retrieve_project_candidates


def _identifier(project: Project, identifier_type: str, value: str):
    return ProjectIdentifier(
        id=uuid4(),
        project_id=project.id,
        identifier_type=identifier_type,
        display_value=value,
        normalized_value=value,
        verified=True,
    )


def test_all_deterministic_paths_remain_project_type_neutral_and_ambiguous() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    contact_repository = MagicMock(spec=ProjectContactRepository)
    conversation_repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    software = Project(
        id=uuid4(),
        project_code="SOFTWARE",
        name="Release Automation",
        normalized_name="release automation",
        status=ProjectStatus.ACTIVE,
    )
    construction = Project(
        id=uuid4(),
        project_code="BUILDING",
        name="Civic Extension",
        normalized_name="civic extension",
        status=ProjectStatus.ACTIVE,
    )
    repository_identifier = _identifier(
        software, "repository", "example/release-automation"
    )
    address_identifier = _identifier(
        construction, "address", "10 example avenue"
    )
    contact = ProjectContact(
        id=uuid4(),
        project_id=software.id,
        email_normalized="person@example.com",
        display_name="Person",
        is_active=True,
    )
    project_repository.find_by_normalized_codes.return_value = [software]
    project_repository.find_by_normalized_names.return_value = [construction]
    identifier_repository.find_verified_exact_with_projects.side_effect = [
        [(repository_identifier, software)],
        [],
        [(address_identifier, construction)],
    ]
    contact_repository.find_active_with_projects.return_value = [(contact, software)]
    conversation_repository.find_approved_projects_for_conversation.return_value = [
        construction
    ]
    query = ProjectCandidateQuery(
        source="fixture",
        external_conversation_id="conversation-1",
        sender_email_normalized="person@example.com",
        project_codes=(
            CandidateValueHint(
                normalized_value="SOFTWARE",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
        normalized_names=(
            CandidateValueHint(
                normalized_value="Civic Extension",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
        ),
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="repository",
                normalized_value="example/release-automation",
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
            ),
            CandidateIdentifierHint(
                identifier_type="address",
                normalized_value="10 example avenue",
                source=CandidateSignalSource.EVIDENCE_ITEM,
                evidence_item_id=uuid4(),
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

    assert result.cardinality is CandidateSetCardinality.MULTIPLE
    assert result.is_ambiguous is True
    signals_by_code = {
        candidate.project_code: {signal.signal_type for signal in candidate.signals}
        for candidate in result.candidates
    }
    assert signals_by_code["SOFTWARE"] == {
        CandidateSignalType.PROJECT_CODE,
        CandidateSignalType.VERIFIED_IDENTIFIER,
        CandidateSignalType.PROJECT_CONTACT,
    }
    assert signals_by_code["BUILDING"] == {
        CandidateSignalType.NORMALIZED_NAME,
        CandidateSignalType.APPROVED_CONVERSATION,
        CandidateSignalType.DOCUMENT_IDENTIFIER,
    }
    assert "address" not in Project.__table__.c
    assert "repository" not in Project.__table__.c
    assert "selected_project_id" not in ProjectCandidateSet.model_fields


def test_arbitrary_identifier_types_flow_through_without_special_case_logic() -> None:
    project_repository = MagicMock(spec=ProjectRepository)
    identifier_repository = MagicMock(spec=ProjectIdentifierRepository)
    contact_repository = MagicMock(spec=ProjectContactRepository)
    conversation_repository = MagicMock(spec=CorrespondenceProjectLinkRepository)
    project = Project(
        id=uuid4(),
        project_code="GENERAL",
        name="General Project",
        normalized_name="general project",
        status=ProjectStatus.ACTIVE,
    )
    identifier = _identifier(project, "custom_reference", "value-9387")
    project_repository.find_by_normalized_codes.return_value = []
    project_repository.find_by_normalized_names.return_value = []
    identifier_repository.find_verified_exact_with_projects.side_effect = [
        [(identifier, project)],
        [],
        [],
    ]
    contact_repository.find_active_with_projects.return_value = []
    conversation_repository.find_approved_projects_for_conversation.return_value = []
    query = ProjectCandidateQuery(
        source="fixture",
        identifiers=(
            CandidateIdentifierHint(
                identifier_type="custom_reference",
                normalized_value="value-9387",
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

    assert result.candidates[0].signals[0].identifier_type == "custom_reference"
