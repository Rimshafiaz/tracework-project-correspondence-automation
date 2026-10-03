import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import Agent, ModelResponse, ToolCallPart, UnexpectedModelBehavior
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.requirement_schemas import ExistingEvidenceReference, ExistingRequirementImpact, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverCorrespondence, ResolverSourceField
from app.contracts.requirement_reconciliation import ExistingRequirementEvidence, RequirementAttachmentContext, RequirementReconcilerInput, RequirementSnapshot
from app.models.enums import AttachmentProcessingState, EvidenceValidity, RequirementState
from app.services.requirement_reconciliation import RequirementReconciliationService, RequirementReconciliationValidationError


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


def _context(body: str = "The final report is complete.") -> RequirementReconcilerInput:
    project_id = uuid4()
    requirement = RequirementSnapshot(
        requirement_id=uuid4(),
        name="Provide final report",
        current_state=RequirementState.OPEN,
    )
    evidence = ExistingRequirementEvidence(
        evidence_item_id=uuid4(),
        correspondence_event_id=uuid4(),
        project_id=project_id,
        requirement_id=requirement.requirement_id,
        source_type="body",
        excerpt="Earlier supporting evidence",
        validity=EvidenceValidity.VALID,
    )
    return RequirementReconcilerInput(
        project_id=project_id,
        authoritative_project_link_id=uuid4(),
        correspondence=ResolverCorrespondence(
            correspondence_event_id=uuid4(),
            source="fixture",
            sender_identifier="sender@example.test",
            body=body,
            received_at=datetime.now(UTC),
        ),
        requirements=(requirement,),
        existing_valid_evidence=(evidence,),
    )


def _source_evidence(
    context: RequirementReconcilerInput,
    excerpt: str,
) -> RequirementSourceEvidence:
    return RequirementSourceEvidence(
        correspondence_event_id=context.correspondence.correspondence_event_id,
        source_field=ResolverSourceField.BODY,
        excerpt=excerpt,
    )


def _agent_returning(
    output: RequirementReconciliation,
) -> Agent[None, RequirementReconciliation]:
    def respond(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    output.model_dump(mode="json"),
                )
            ]
        )

    return Agent(FunctionModel(respond), output_type=RequirementReconciliation)


def _service(
    output: RequirementReconciliation,
    repository: FakeLineageRepository | None = None,
) -> RequirementReconciliationService:
    return RequirementReconciliationService(
        agent=_agent_returning(output),
        lineage_repository=repository or FakeLineageRepository(),
        model_identifier="google:test-model",
    )


def test_validates_real_change_and_computes_offsets() -> None:
    context = _context()
    excerpt = "final report is complete"
    output = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.SATISFIED,
                evidence=(_source_evidence(context, excerpt),),
                interpretation="The report appears complete.",
            ),
        )
    )

    result = asyncio.run(_service(output).reconcile(context))

    validated = result.validated_source_evidence[0]
    assert validated.start_offset == context.correspondence.body.index(excerpt)
    assert validated.end_offset == validated.start_offset + len(excerpt)
    assert context.requirements[0].current_state is RequirementState.OPEN


def test_persists_proposal_snapshot_lineage_and_audit_after_validation() -> None:
    from app.contracts.requirement_reconciliation import reconstruct_requirement_context_snapshot
    from app.models.enums import ProposalType

    context = _context()
    existing_evidence_id = context.existing_valid_evidence[0].evidence_item_id
    excerpt = "final report is complete"
    output = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.SATISFIED,
                evidence=(
                    _source_evidence(context, excerpt),
                    ExistingEvidenceReference(evidence_item_id=existing_evidence_id),
                ),
                interpretation="The report appears complete.",
            ),
        )
    )
    repository = FakeLineageRepository()

    result = asyncio.run(_service(output, repository).reconcile(context))

    assert len(repository.evidence) == 1
    assert repository.evidence[0].requirement_id == context.requirements[0].requirement_id
    assert len(repository.proposals) == 1
    proposal = repository.proposals[0]
    assert result.proposal is proposal
    assert proposal.proposal_type is ProposalType.REQUIREMENT_RECONCILIATION
    assert proposal.model_identifier == "google:test-model"
    assert proposal.prompt_version == "requirement-reconciler-v1"
    assert len(proposal.input_hash) == 64
    assert set(proposal.evidence_item_ids) == {
        repository.evidence[0].id,
        existing_evidence_id,
    }
    snapshot = reconstruct_requirement_context_snapshot(proposal.input_metadata)
    assert snapshot.project_id == context.project_id
    assert proposal.structured_output == output.model_dump(mode="json")
    assert repository.audit_events[0].event_type == "requirement_reconciliation_proposed"
    assert context.requirements[0].current_state is RequirementState.OPEN


def test_rejects_unknown_requirement_and_non_change() -> None:
    context = _context()
    evidence = _source_evidence(context, "final report is complete")
    unknown = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=uuid4(),
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.SATISFIED,
                evidence=(evidence,),
                interpretation="Unknown requirement.",
            ),
        )
    )
    repository = FakeLineageRepository()
    with pytest.raises(RequirementReconciliationValidationError, match="outside"):
        asyncio.run(_service(unknown, repository).reconcile(context))
    assert repository.evidence == repository.proposals == repository.audit_events == []

    unchanged = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.OPEN,
                evidence=(evidence,),
                interpretation="No real change.",
            ),
        )
    )
    with pytest.raises(RequirementReconciliationValidationError, match="must change"):
        asyncio.run(_service(unchanged, repository).reconcile(context))
    assert repository.evidence == repository.proposals == repository.audit_events == []


def test_rejects_unknown_existing_evidence() -> None:
    context = _context()
    output = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.PARTIAL,
                evidence=(ExistingEvidenceReference(evidence_item_id=uuid4()),),
                interpretation="Unsupported evidence reference.",
            ),
        )
    )

    with pytest.raises(RequirementReconciliationValidationError, match="not supplied"):
        asyncio.run(_service(output).reconcile(context))


@pytest.mark.parametrize(
    "body,excerpt,message",
    [
        ("The report is pending.", "report is complete", "does not occur"),
        ("complete, then complete again", "complete", "more than once"),
    ],
)
def test_rejects_invented_or_ambiguous_excerpt(body, excerpt, message) -> None:
    context = _context(body)
    output = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.SATISFIED,
                evidence=(_source_evidence(context, excerpt),),
                interpretation="Claimed completion.",
            ),
        )
    )

    with pytest.raises(RequirementReconciliationValidationError, match=message):
        asyncio.run(_service(output).reconcile(context))


def test_preserves_reliable_pdf_page_provenance() -> None:
    context = _context("See the attached report.")
    text = "The attached report is complete."
    attachment = RequirementAttachmentContext(
        attachment_id=uuid4(),
        filename="report.pdf",
        mime_type="application/pdf",
        processing_state=AttachmentProcessingState.EXTRACTED,
        extracted_text=text,
        extraction_metadata={
            "pdf_segments": [
                {
                    "page_number": 4,
                    "text_start": 0,
                    "text_end": len(text),
                    "text": text,
                }
            ]
        },
        content_hash="a" * 64,
    )
    context = context.model_copy(update={"attachments": (attachment,)})
    evidence = RequirementSourceEvidence(
        correspondence_event_id=context.correspondence.correspondence_event_id,
        source_field=ResolverSourceField.ATTACHMENT_TEXT,
        attachment_id=attachment.attachment_id,
        excerpt="report is complete",
    )
    output = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.SATISFIED,
                evidence=(evidence,),
                interpretation="The attached report appears complete.",
            ),
        )
    )

    result = asyncio.run(_service(output).reconcile(context))

    assert result.validated_source_evidence[0].page_number == 4


def test_provider_failure_creates_no_lineage_records() -> None:
    context = _context()
    repository = FakeLineageRepository()

    def fail(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider unavailable")

    service = RequirementReconciliationService(
        agent=Agent(FunctionModel(fail), output_type=RequirementReconciliation),
        lineage_repository=repository,
        model_identifier="google:test-model",
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(service.reconcile(context))
    assert repository.evidence == repository.proposals == repository.audit_events == []


def test_malformed_output_creates_no_lineage_records() -> None:
    context = _context()
    repository = FakeLineageRepository()

    def malformed(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"unexpected": True})]
        )

    service = RequirementReconciliationService(
        agent=Agent(
            FunctionModel(malformed),
            output_type=RequirementReconciliation,
            retries={"output": 1},
        ),
        lineage_repository=repository,
        model_identifier="google:test-model",
    )

    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(service.reconcile(context))
    assert repository.evidence == repository.proposals == repository.audit_events == []
