import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import httpx
from groq import APIConnectionError as GroqAPIConnectionError
from pydantic_ai import Agent, ModelResponse, ToolCallPart, UnexpectedModelBehavior
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.schemas import CandidateSignalReference, EvidenceConflict, ProjectResolution, ProjectResolverInput, ResolutionConcern, ResolutionEvidence, ResolutionStatus, ResolverAttachment, ResolverCorrespondence, ResolverSourceField, SourceTextEvidence
from app.ai.prompts.project_resolver import PROJECT_RESOLVER_INSTRUCTIONS, PROJECT_RESOLVER_PROMPT_VERSION
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal, reconstruct_project_candidate_snapshot
from app.models.enums import AttachmentProcessingState, ProjectStatus
from app.services import project_resolution
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


def test_prompt_prefers_supplied_signals_and_requires_verbatim_single_field_quotes() -> None:
    assert PROJECT_RESOLVER_PROMPT_VERSION == "project-resolver-v2"
    for instruction in (
        "Prefer the supplied typed candidate signal references",
        "one contiguous substring verbatim",
        "Preserve every character",
        "punctuation mark, space, and line break",
        "Never paraphrase",
        "combine subject, body, or attachment",
        "omit the source excerpt",
    ):
        assert instruction in PROJECT_RESOLVER_INSTRUCTIONS


def test_project_code_and_trusted_contact_support_signal_only_resolution() -> None:
    candidate = _candidate("TW-002")
    contact = ProjectCandidateSignal(
        signal_type=CandidateSignalType.PROJECT_CONTACT,
        matched_value="sender@example.test",
        source=CandidateSignalSource.PROJECT_RECORD,
        source_record_id=uuid4(),
        exact=True,
    )
    candidate = candidate.model_copy(update={"signals": (*candidate.signals, contact)})
    context = _context("The body names TW-002.", candidate)
    code_reference = _signal_reference(candidate)
    contact_reference = CandidateSignalReference(
        project_id=candidate.project_id,
        signal_type=contact.signal_type,
        matched_value=contact.matched_value,
        source=contact.source,
        source_record_id=contact.source_record_id,
    )
    resolution = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(code_reference, contact_reference),
                interpretation="The supplied code and contact identify this candidate.",
            ),
        ),
    )
    repository = FakeLineageRepository()

    result = asyncio.run(_service(resolution, repository).resolve(context))

    assert result.resolution.project_ids == (candidate.project_id,)
    assert repository.proposals[0].prompt_version == PROJECT_RESOLVER_PROMPT_VERSION
    assert repository.proposals[0].structured_output["evidence"][0]["source_evidence"] == []
    assert {item.source_type for item in repository.evidence} == {
        "candidate_signal:project_code",
        "candidate_signal:project_contact",
    }


@pytest.mark.parametrize(
    ("subject", "body", "source_field", "excerpt"),
    (
        ("Project update", "Project TW-002 is ready.", ResolverSourceField.BODY, "Project TW-002 was approved."),
        ("Project update", "TW-002 is ready.", ResolverSourceField.BODY, "TW-002  is ready."),
        ("Project update", "TW-002 is ready.", ResolverSourceField.BODY, "TW-002, is ready."),
        ("Project update", "TW-002 is ready.", ResolverSourceField.BODY, "Project update TW-002"),
    ),
    ids=("paraphrase", "whitespace", "punctuation", "cross-field"),
)
def test_inexact_source_excerpt_is_rejected_before_persistence(
    subject: str,
    body: str,
    source_field: ResolverSourceField,
    excerpt: str,
) -> None:
    candidate = _candidate("TW-002")
    context = _context(body, candidate)
    context = context.model_copy(
        update={
            "correspondence": context.correspondence.model_copy(
                update={"subject": subject}
            )
        }
    )
    resolution = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_signal_reference(candidate),),
                source_evidence=(
                    SourceTextEvidence(
                        correspondence_event_id=context.correspondence.correspondence_event_id,
                        source_field=source_field,
                        excerpt=excerpt,
                    ),
                ),
                interpretation="The candidate signal refers to this project.",
            ),
        ),
    )
    repository = FakeLineageRepository()

    with pytest.raises(ProjectResolutionValidationError, match="does not occur"):
        asyncio.run(_service(resolution, repository).resolve(context))

    assert repository.evidence == []
    assert repository.proposals == []


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


def _provider_retry_service(
    outcomes: list[ProjectResolution | Exception],
    repository: FakeLineageRepository,
    calls: list[int],
) -> ProjectResolutionService:
    def respond(messages, info: AgentInfo) -> ModelResponse:
        calls.append(len(calls) + 1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    outcome.model_dump(mode="json"),
                )
            ]
        )

    return ProjectResolutionService(
        agent=Agent(FunctionModel(respond), output_type=ProjectResolution),
        lineage_repository=repository,
        model_identifier="google:test-model",
    )


def _signal_only_resolution(candidate: ProjectCandidate) -> ProjectResolution:
    return ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_signal_reference(candidate),),
                interpretation="The supplied project-code signal identifies the project.",
            ),
        ),
    )


@pytest.mark.parametrize("transient_failures", (1, 2))
def test_transient_provider_failure_retries_until_success(
    monkeypatch, transient_failures: int
) -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    resolution = _signal_only_resolution(candidate)
    provider_error = ModelHTTPError(503, "gemini-test", {"status": "UNAVAILABLE"})
    calls = []
    sleeps = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(project_resolution.asyncio, "sleep", fake_sleep)
    outcomes = [
        *(provider_error for _ in range(transient_failures)),
        resolution,
    ]

    result = asyncio.run(
        _provider_retry_service(outcomes, FakeLineageRepository(), calls).resolve(
            context
        )
    )

    assert result.resolution == resolution
    assert len(calls) == transient_failures + 1
    assert sleeps == [0.5, 1.0][:transient_failures]


def test_temporary_transport_failure_is_retried(monkeypatch) -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    resolution = _signal_only_resolution(candidate)
    calls = []
    sleeps = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(project_resolution.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        _provider_retry_service(
            [httpx.ConnectError("temporary connection failure"), resolution],
            FakeLineageRepository(),
            calls,
        ).resolve(context)
    )

    assert result.resolution == resolution
    assert calls == [1, 2]
    assert sleeps == [0.5]


def test_groq_sdk_connection_error_is_retryable() -> None:
    error = ModelAPIError(model_name="groq:test", message="connection failed")
    error.__cause__ = GroqAPIConnectionError(
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    )

    assert ProjectResolutionService._is_retryable_provider_error(error) is True


def test_three_transient_provider_failures_propagate_final_error(
    monkeypatch,
) -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    repository = FakeLineageRepository()
    calls = []
    sleeps = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(project_resolution.asyncio, "sleep", fake_sleep)
    failures = [
        ModelHTTPError(503, "gemini-test", {"status": "UNAVAILABLE"})
        for _ in range(3)
    ]

    with pytest.raises(ModelHTTPError) as error:
        asyncio.run(
            _provider_retry_service(failures, repository, calls).resolve(context)
        )

    assert error.value.status_code == 503
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]
    assert repository.proposals == []


def test_non_transient_provider_error_is_not_retried(monkeypatch) -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    calls = []

    async def fail_if_called(_delay: float) -> None:
        raise AssertionError("non-transient failure must not sleep")

    monkeypatch.setattr(project_resolution.asyncio, "sleep", fail_if_called)

    with pytest.raises(ModelHTTPError) as error:
        asyncio.run(
            _provider_retry_service(
                [ModelHTTPError(400, "gemini-test", {"status": "INVALID_ARGUMENT"})],
                FakeLineageRepository(),
                calls,
            ).resolve(context)
        )

    assert error.value.status_code == 400
    assert calls == [1]


def test_grounding_validation_failure_does_not_retry_provider(monkeypatch) -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    invalid = ProjectResolution(
        status=ResolutionStatus.MATCHED,
        project_ids=(candidate.project_id,),
        evidence=(
            ResolutionEvidence(
                project_id=candidate.project_id,
                source_evidence=(_body_evidence(context, "invented text"),),
                interpretation="Invalid source evidence.",
            ),
        ),
    )
    calls = []

    async def fail_if_called(_delay: float) -> None:
        raise AssertionError("validation failure must not sleep")

    monkeypatch.setattr(project_resolution.asyncio, "sleep", fail_if_called)

    with pytest.raises(ProjectResolutionValidationError, match="does not occur"):
        asyncio.run(
            _provider_retry_service(
                [invalid], FakeLineageRepository(), calls
            ).resolve(context)
        )

    assert calls == [1]


def test_normal_provider_success_executes_once(monkeypatch) -> None:
    candidate = _candidate("ALPHA")
    context = _context("The message names ALPHA.", candidate)
    resolution = _signal_only_resolution(candidate)
    calls = []

    async def fail_if_called(_delay: float) -> None:
        raise AssertionError("successful provider call must not sleep")

    monkeypatch.setattr(project_resolution.asyncio, "sleep", fail_if_called)

    result = asyncio.run(
        _provider_retry_service(
            [resolution], FakeLineageRepository(), calls
        ).resolve(context)
    )

    assert result.resolution == resolution
    assert calls == [1]


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
