from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent

from app.ai.schemas import ProjectResolution, ProjectResolverInput, ResolutionConcern, ResolutionStatus, ResolverAttachment, ResolverCorrespondence
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal
from app.evaluation.contracts import EvaluationCase
from app.evaluation.datasets import DatasetSplit, load_dataset
from app.models.enums import AttachmentProcessingState, ProjectStatus


class ResolverEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    actual_status: ResolutionStatus
    actual_project_ids: tuple[str, ...]
    status_matches: bool
    projects_match_when_labeled: bool


def _fixture_uuid(kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tracework-evaluation:{kind}:{value}")


def build_project_resolver_input(
    case: EvaluationCase,
) -> tuple[ProjectResolverInput, dict[UUID, str]]:
    correspondence = case.input.correspondence
    project_ids = {
        project.project_id: _fixture_uuid("project", project.project_id)
        for project in case.input.candidate_projects
    }
    reverse_project_ids = {value: key for key, value in project_ids.items()}
    candidates = []
    for project in case.input.candidate_projects:
        signals = []
        for identifier in project.identifiers:
            if identifier.verified:
                signals.append(
                    ProjectCandidateSignal(
                        signal_type=CandidateSignalType.VERIFIED_IDENTIFIER,
                        matched_value=identifier.normalized_value,
                        source=CandidateSignalSource.PROJECT_RECORD,
                        identifier_type=identifier.identifier_type,
                        source_record_id=_fixture_uuid(
                            "identifier",
                            f"{project.project_id}:{identifier.identifier_type}:{identifier.normalized_value}",
                        ),
                        exact=True,
                        verified=True,
                    )
                )
        if correspondence.sender_identifier in project.known_contact_identifiers:
            signals.append(
                ProjectCandidateSignal(
                    signal_type=CandidateSignalType.PROJECT_CONTACT,
                    matched_value=correspondence.sender_identifier,
                    source=CandidateSignalSource.PROJECT_RECORD,
                    source_record_id=_fixture_uuid(
                        "contact",
                        f"{project.project_id}:{correspondence.sender_identifier}",
                    ),
                    exact=True,
                )
            )
        if not signals:
            signals.append(
                ProjectCandidateSignal(
                    signal_type=CandidateSignalType.NORMALIZED_NAME,
                    matched_value=project.normalized_name,
                    source=CandidateSignalSource.PROJECT_RECORD,
                    exact=True,
                )
            )
        candidates.append(
            ProjectCandidate(
                project_id=project_ids[project.project_id],
                project_code=project.project_code,
                project_name=project.name,
                project_status=ProjectStatus.ACTIVE,
                signals=tuple(signals),
            )
        )

    attachments = tuple(
        ResolverAttachment(
            attachment_id=_fixture_uuid("attachment", attachment.attachment_id),
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            processing_state=(
                AttachmentProcessingState.EXTRACTED
                if attachment.extracted_text
                else AttachmentProcessingState.UNSUPPORTED
            ),
            extracted_text=attachment.extracted_text,
        )
        for attachment in correspondence.attachments
    )
    context = ProjectResolverInput(
        correspondence=ResolverCorrespondence(
            correspondence_event_id=_fixture_uuid(
                "correspondence",
                correspondence.external_event_id,
            ),
            source=correspondence.source,
            external_conversation_id=correspondence.external_conversation_id,
            sender_identifier=correspondence.sender_identifier,
            sender_name=correspondence.sender_name,
            sender_email=correspondence.sender_email,
            subject=correspondence.subject,
            body=correspondence.body,
            received_at=correspondence.received_at,
        ),
        candidates=ProjectCandidateSet(candidates=tuple(candidates)),
        attachments=attachments,
    )
    return context, reverse_project_ids


async def run_project_resolver_development_set(
    agent: Agent[None, ProjectResolution],
) -> tuple[ResolverEvaluationResult, ...]:
    results = []
    for case in load_dataset(DatasetSplit.DEVELOPMENT):
        context, reverse_project_ids = build_project_resolver_input(case)
        if context.candidates.candidates:
            resolution = (await agent.run(context.model_dump_json())).output
        else:
            resolution = ProjectResolution(
                status=ResolutionStatus.NO_MATCH,
                concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
            )
        actual_project_ids = tuple(
            reverse_project_ids[project_id]
            for project_id in resolution.project_ids
            if project_id in reverse_project_ids
        )
        expected_project_ids = case.expected.project_ids
        results.append(
            ResolverEvaluationResult(
                case_id=case.case_id,
                actual_status=resolution.status,
                actual_project_ids=actual_project_ids,
                status_matches=resolution.status.value
                == case.expected.project_resolution.value,
                projects_match_when_labeled=(
                    not expected_project_ids
                    or set(actual_project_ids) == set(expected_project_ids)
                ),
            )
        )
    return tuple(results)
