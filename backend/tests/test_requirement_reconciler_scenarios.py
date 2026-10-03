import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from pydantic_ai import Agent, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.ai.requirement_schemas import ExistingRequirementImpact, NewRequirementProposal, RequirementEvidenceConflict, RequirementImpactDisposition, RequirementReconciliation, RequirementReconciliationConcern, RequirementReconciliationConcernType, RequirementSourceEvidence
from app.ai.schemas import ResolverCorrespondence, ResolverSourceField
from app.contracts.requirement_reconciliation import RequirementReconcilerInput, RequirementSnapshot
from app.models.enums import RequirementState
from app.services.requirement_reconciliation import RequirementReconciliationService


class RecordingLineageRepository:
    def __init__(self) -> None:
        self.evidence = []
        self.proposals = []
        self.audits = []

    def create_evidence(self, **values):
        item = SimpleNamespace(id=uuid4(), **values)
        self.evidence.append(item)
        return item

    def create_proposal(self, **values):
        item = SimpleNamespace(id=uuid4(), **values)
        self.proposals.append(item)
        return item

    def create_audit_event(self, **values):
        self.audits.append(values)


def _context(body: str, requirement_count: int = 1) -> RequirementReconcilerInput:
    return RequirementReconcilerInput(
        project_id=uuid4(),
        authoritative_project_link_id=uuid4(),
        correspondence=ResolverCorrespondence(
            correspondence_event_id=uuid4(),
            source="fixture",
            sender_identifier="sender@example.test",
            body=body,
            received_at=datetime.now(UTC),
        ),
        requirements=tuple(
            RequirementSnapshot(
                requirement_id=uuid4(),
                name=f"Requirement {index + 1}",
                description=f"Neutral obligation {index + 1}",
                current_state=RequirementState.OPEN,
            )
            for index in range(requirement_count)
        ),
    )


def _evidence(
    context: RequirementReconcilerInput,
    excerpt: str,
) -> RequirementSourceEvidence:
    return RequirementSourceEvidence(
        correspondence_event_id=context.correspondence.correspondence_event_id,
        source_field=ResolverSourceField.BODY,
        excerpt=excerpt,
    )


def _run(context: RequirementReconcilerInput, output: RequirementReconciliation):
    def respond(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    output.model_dump(mode="json"),
                )
            ]
        )

    repository = RecordingLineageRepository()
    service = RequirementReconciliationService(
        agent=Agent(FunctionModel(respond), output_type=RequirementReconciliation),
        lineage_repository=repository,
        model_identifier="function:test-scenario",
    )
    return asyncio.run(service.reconcile(context)), repository


def test_clear_satisfied_and_partial_scenarios_remain_distinct() -> None:
    for body, excerpt, state in (
        (
            "The final review is complete and every finding is closed.",
            "every finding is closed",
            RequirementState.SATISFIED,
        ),
        (
            "The report is supplied, but verification is still pending.",
            "verification is still pending",
            RequirementState.PARTIAL,
        ),
    ):
        context = _context(body)
        output = RequirementReconciliation(
            existing_impacts=(
                ExistingRequirementImpact(
                    requirement_id=context.requirements[0].requirement_id,
                    disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                    proposed_state=state,
                    evidence=(_evidence(context, excerpt),),
                    interpretation="The correspondence supports this state.",
                ),
            )
        )

        result, _ = _run(context, output)

        assert result.reconciliation.existing_impacts[0].proposed_state is state


def test_future_intent_and_unrelated_correspondence_do_not_force_changes() -> None:
    context = _context("We plan to provide the report next week.")
    no_change = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.NO_CHANGE,
                evidence=(_evidence(context, "plan to provide the report next week"),),
                interpretation="Future intent does not establish completion.",
            ),
        )
    )
    result, _ = _run(context, no_change)
    assert result.reconciliation.existing_impacts[0].proposed_state is None

    unrelated_context = _context("Thank you for the meeting notes.")
    result, repository = _run(unrelated_context, RequirementReconciliation())
    assert result.reconciliation.existing_impacts == ()
    assert repository.evidence == []


def test_one_correspondence_can_affect_multiple_requirements() -> None:
    context = _context("Item one is complete. Item two is partly complete.", 2)
    output = RequirementReconciliation(
        existing_impacts=tuple(
            ExistingRequirementImpact(
                requirement_id=requirement.requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=state,
                evidence=(_evidence(context, excerpt),),
                interpretation="The item status is explicit.",
            )
            for requirement, state, excerpt in zip(
                context.requirements,
                (RequirementState.SATISFIED, RequirementState.PARTIAL),
                ("Item one is complete", "Item two is partly complete"),
                strict=True,
            )
        )
    )

    result, repository = _run(context, output)

    assert len(result.reconciliation.existing_impacts) == 2
    assert len(repository.evidence) == 2


def test_ambiguity_and_conflicting_evidence_remain_explicit() -> None:
    context = _context("The work is complete, but the final check is still pending.", 2)
    complete = _evidence(context, "work is complete")
    pending = _evidence(context, "final check is still pending")
    output = RequirementReconciliation(
        concerns=(
            RequirementReconciliationConcern(
                concern_type=RequirementReconciliationConcernType.AMBIGUOUS_REQUIREMENT_MAPPING,
                candidate_requirement_ids=tuple(
                    item.requirement_id for item in context.requirements
                ),
                evidence=(complete,),
                description="The completion statement could map to either requirement.",
            ),
        ),
        conflicts=(
            RequirementEvidenceConflict(
                requirement_ids=(context.requirements[0].requirement_id,),
                evidence=(complete, pending),
                description="Completion and pending qualification conflict.",
            ),
        ),
    )

    result, _ = _run(context, output)

    assert result.reconciliation.concerns[0].concern_type is RequirementReconciliationConcernType.AMBIGUOUS_REQUIREMENT_MAPPING
    assert len(result.reconciliation.conflicts) == 1


def test_new_scope_is_a_proposal_but_paraphrase_maps_to_existing_requirement() -> None:
    new_context = _context("Please provide a recurring monthly summary.")
    new_output = RequirementReconciliation(
        new_requirements=(
            NewRequirementProposal(
                name="Provide recurring monthly summary",
                evidence=(_evidence(new_context, "recurring monthly summary"),),
                interpretation="The correspondence introduces a new recurring obligation.",
            ),
        )
    )
    result, _ = _run(new_context, new_output)
    assert len(result.reconciliation.new_requirements) == 1

    existing_context = _context("The final deliverable has now been supplied.")
    existing_output = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=existing_context.requirements[0].requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.SATISFIED,
                evidence=(_evidence(existing_context, "has now been supplied"),),
                interpretation="Paraphrased wording maps to the existing obligation.",
            ),
        )
    )
    result, _ = _run(existing_context, existing_output)
    assert result.reconciliation.new_requirements == ()
