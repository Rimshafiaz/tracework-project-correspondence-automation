import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic_ai import Agent, ModelResponse, ToolCallPart, UnexpectedModelBehavior
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.schemas import CandidateSignalReference, EvidenceConflict, ProjectResolution, ProjectResolverInput, ResolutionConcern, ResolutionEvidence, ResolutionStatus, ResolverAttachment, ResolverCorrespondence, ResolverSourceField, SourceTextEvidence
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal, reconstruct_project_candidate_snapshot
from app.models.enums import AttachmentProcessingState, ProjectStatus
from app.services.project_resolution import DETERMINISTIC_NO_CANDIDATES_MODEL, ProjectResolutionService, ProjectResolutionValidationError


class FakeLineageRepository:
    def __init__(self) -> None:
        self.evidence = []
        self.proposals = []
        self.audit_events = []

    def create_evidence(self, **values):
        item = SimpleNamespace(id=uuid4(), **values)
        self.evidence.append(item)
        return item

    def create_proposal(self, **values):
        item = SimpleNamespace(id=uuid4(), **values)
        self.proposals.append(item)
        return item

    def create_audit_event(self, **values):
        item = SimpleNamespace(id=uuid4(), **values)
        self.audit_events.append(item)
        return item


def _candidate(code: str) -> ProjectCandidate:
    return ProjectCandidate(
        project_id=uuid4(),
        project_code=code,
        project_name=f"Example {code}",
        project_status=ProjectStatus.ACTIVE,
        signals=(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.PROJECT_CODE,
                matched_value=code,
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                exact=True,
            ),
        ),
    )


def _context(
    body: str,
    *candidates: ProjectCandidate,
    attachment: ResolverAttachment | None = None,
) -> ProjectResolverInput:
    return ProjectResolverInput(
        correspondence=ResolverCorrespondence(
            correspondence_event_id=uuid4(),
            source="fixture",
            external_conversation_id="conversation-example",
            sender_identifier="sender@example.test",
            sender_email="sender@example.test",
            subject="Project update",
            body=body,
            received_at=datetime.now(UTC),
        ),
        candidates=ProjectCandidateSet(candidates=candidates),
        attachments=(attachment,) if attachment is not None else (),
    )


def _signal_reference(candidate: ProjectCandidate) -> CandidateSignalReference:
    signal = candidate.signals[0]
    return CandidateSignalReference(
        project_id=candidate.project_id,
        signal_type=signal.signal_type,
        matched_value=signal.matched_value,
        source=signal.source,
        identifier_type=signal.identifier_type,
        source_record_id=signal.source_record_id,
        attachment_id=signal.attachment_id,
        evidence_item_id=signal.evidence_item_id,
    )


def _body_evidence(context: ProjectResolverInput, excerpt: str) -> SourceTextEvidence:
    return SourceTextEvidence(
        correspondence_event_id=context.correspondence.correspondence_event_id,
        source_field=ResolverSourceField.BODY,
        excerpt=excerpt,
    )


def _agent_returning(
    output: ProjectResolution,
    calls: list[bool] | None = None,
) -> Agent[None, ProjectResolution]:
    def respond(messages, info: AgentInfo) -> ModelResponse:
        if calls is not None:
            calls.append(True)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    output.model_dump(mode="json"),
                )
            ]
        )

    return Agent(FunctionModel(respond), output_type=ProjectResolution)


def _service(
    output: ProjectResolution,
    repository: FakeLineageRepository,
    calls: list[bool] | None = None,
) -> ProjectResolutionService:
    return ProjectResolutionService(
        agent=_agent_returning(output, calls),
        lineage_repository=repository,
        model_identifier="google:test-model",
    )


def test_clear_match_validates_excerpt_computes_offsets_and_persists_proposal() -> None:
    candidate = _candidate("ALPHA")
    context = _context("Please apply this update to ALPHA today.", candidate)
    resolution = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_signal_reference(candidate),),
                source_evidence=(_body_evidence(context, "ALPHA"),),
                interpretation="The body names the supplied project code.",
            ),
        ),
    )
    repository = FakeLineageRepository()

    result = asyncio.run(_service(resolution, repository).resolve(context))

    assert result.agent_invoked is True
    assert result.resolution.status is ResolutionStatus.MATCHED
    text_evidence = next(
        item
        for item in repository.evidence
        if item.excerpt == "ALPHA" and item.source_type == "body"
    )
    assert text_evidence.provenance_metadata["start_offset"] == context.correspondence.body.index("ALPHA")
    assert text_evidence.provenance_metadata["end_offset"] == context.correspondence.body.index("ALPHA") + 5
    assert repository.proposals[0].structured_output["status"] == "MATCHED"
    assert (
        reconstruct_project_candidate_snapshot(
            repository.proposals[0].input_metadata
        )
        == context.candidates
    )
    assert repository.audit_events[0].details["agent_invoked"] is True


def test_empty_candidate_set_short_circuits_agent_and_persists_no_match() -> None:
    context = _context("No recognizable project reference.")
    calls = []
    repository = FakeLineageRepository()
    unused_output = ProjectResolution(
        status=ResolutionStatus.NO_MATCH,
        concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
    )

    result = asyncio.run(
        _service(unused_output, repository, calls).resolve(context)
    )

    assert calls == []
    assert result.agent_invoked is False
    assert result.resolution.status is ResolutionStatus.NO_MATCH
    assert repository.proposals[0].model_identifier == DETERMINISTIC_NO_CANDIDATES_MODEL


def test_one_candidate_still_invokes_agent_and_can_return_no_match() -> None:
    candidate = _candidate("ALPHA")
    context = _context("This message concerns something else.", candidate)
    calls = []
    resolution = ProjectResolution(
        status=ResolutionStatus.NO_MATCH,
        concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
    )

    result = asyncio.run(
        _service(resolution, FakeLineageRepository(), calls).resolve(context)
    )

    assert calls == [True]
    assert result.resolution.status is ResolutionStatus.NO_MATCH


def test_ambiguous_candidates_remain_review_required() -> None:
    first = _candidate("ALPHA")
    second = _candidate("BETA")
    context = _context("This could concern ALPHA or BETA.", first, second)
    resolution = ProjectResolution(
        status=ResolutionStatus.REVIEW_REQUIRED,
        project_ids=(first.project_id, second.project_id),
        evidence=tuple(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_signal_reference(candidate),),
                source_evidence=(_body_evidence(context, candidate.project_code),),
                interpretation="The message names this candidate.",
            )
            for candidate in (first, second)
        ),
        concerns=(ResolutionConcern.AMBIGUOUS_CANDIDATES,),
    )

    result = asyncio.run(
        _service(resolution, FakeLineageRepository()).resolve(context)
    )

    assert result.resolution.status is ResolutionStatus.REVIEW_REQUIRED
    assert len(result.resolution.project_ids) == 2


def test_conflicting_body_and_attachment_evidence_preserves_m6_page() -> None:
    first = _candidate("ALPHA")
    second = _candidate("BETA")
    attachment_id = uuid4()
    attachment = ResolverAttachment(
        attachment_id=attachment_id,
        filename="update.pdf",
        mime_type="application/pdf",
        processing_state=AttachmentProcessingState.EXTRACTED,
        extracted_text="The document identifies BETA.",
        extraction_metadata={
            "pdf_segments": [
                {
                    "page_number": 4,
                    "text_start": 0,
                    "text_end": 29,
                    "text": "The document identifies BETA.",
                }
            ]
        },
    )
    context = _context("The message identifies ALPHA.", first, second, attachment=attachment)
    body_evidence = _body_evidence(context, "ALPHA")
    attachment_evidence = SourceTextEvidence(
        correspondence_event_id=context.correspondence.correspondence_event_id,
        source_field=ResolverSourceField.ATTACHMENT_TEXT,
        attachment_id=attachment_id,
        excerpt="BETA",
    )
    resolution = ProjectResolution(
        status=ResolutionStatus.REVIEW_REQUIRED,
        project_ids=(first.project_id, second.project_id),
        evidence=(
            ResolutionEvidence(
                project_id=first.project_id,
                source_evidence=(body_evidence,),
                interpretation="The body names ALPHA.",
            ),
            ResolutionEvidence(
                project_id=second.project_id,
                source_evidence=(attachment_evidence,),
                interpretation="The attachment names BETA.",
            ),
        ),
        conflicts=(
            EvidenceConflict(
                project_ids=(first.project_id, second.project_id),
                source_evidence=(body_evidence, attachment_evidence),
                description="Body and attachment identify different candidates.",
            ),
        ),
        concerns=(ResolutionConcern.CONFLICTING_EVIDENCE,),
    )
    repository = FakeLineageRepository()

    asyncio.run(_service(resolution, repository).resolve(context))

    attachment_item = next(item for item in repository.evidence if item.excerpt == "BETA")
    assert attachment_item.page_number == 4
    assert attachment_item.section is None


def test_genuine_multiple_project_correspondence_is_representable() -> None:
    first = _candidate("ALPHA")
    second = _candidate("BETA")
    context = _context("Please update both ALPHA and BETA.", first, second)
    resolution = ProjectResolution(
        status=ResolutionStatus.MULTI_PROJECT,
        project_ids=(first.project_id, second.project_id),
        evidence=tuple(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_signal_reference(candidate),),
                source_evidence=(_body_evidence(context, candidate.project_code),),
                interpretation="The message explicitly includes this project.",
            )
            for candidate in (first, second)
        ),
    )

    result = asyncio.run(
        _service(resolution, FakeLineageRepository()).resolve(context)
    )

    assert result.resolution.status is ResolutionStatus.MULTI_PROJECT


def test_unknown_project_is_rejected_before_persistence() -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    unknown_id = uuid4()
    unknown_resolution = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(unknown_id,),
        evidence=(
            ResolutionEvidence(
                project_id=unknown_id,
                source_evidence=(_body_evidence(context, "ALPHA"),),
                interpretation="Unknown project.",
            ),
        ),
    )
    repository = FakeLineageRepository()

    with pytest.raises(ProjectResolutionValidationError, match="outside"):
        asyncio.run(_service(unknown_resolution, repository).resolve(context))
    assert repository.proposals == []


def test_repeated_excerpt_without_unique_provenance_is_rejected() -> None:
    candidate = _candidate("ALPHA")
    context = _context("ALPHA appears once, then ALPHA appears again.", candidate)
    resolution = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                source_evidence=(_body_evidence(context, "ALPHA"),),
                interpretation="The repeated excerpt is not uniquely located.",
            ),
        ),
    )
    repository = FakeLineageRepository()

    with pytest.raises(ProjectResolutionValidationError, match="more than once"):
        asyncio.run(_service(resolution, repository).resolve(context))

    assert repository.evidence == []
    assert repository.proposals == []


def test_invented_excerpt_is_rejected_before_persistence() -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    repository = FakeLineageRepository()

    invalid_excerpt_resolution = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                source_evidence=(_body_evidence(context, "invented text"),),
                interpretation="Invented evidence.",
            ),
        ),
    )
    with pytest.raises(ProjectResolutionValidationError, match="does not occur"):
        asyncio.run(_service(invalid_excerpt_resolution, repository).resolve(context))
    assert repository.proposals == []


def test_provider_failure_does_not_persist_a_proposal() -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    repository = FakeLineageRepository()

    def fail(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider unavailable")

    service = ProjectResolutionService(
        agent=Agent(FunctionModel(fail), output_type=ProjectResolution),
        lineage_repository=repository,
        model_identifier="google:test-model",
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(service.resolve(context))
    assert repository.proposals == []


def test_malformed_model_output_exhausts_retries_without_persistence() -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    repository = FakeLineageRepository()

    def malformed(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"unexpected": True})]
        )

    service = ProjectResolutionService(
        agent=Agent(
            FunctionModel(malformed),
            output_type=ProjectResolution,
            retries={"output": 1},
        ),
        lineage_repository=repository,
        model_identifier="google:test-model",
    )

    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(service.resolve(context))
    assert repository.proposals == []
