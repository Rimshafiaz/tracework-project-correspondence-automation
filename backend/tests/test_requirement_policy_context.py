from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.requirement_schemas import ExistingRequirementImpact, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverCorrespondence, ResolverSourceField
from app.contracts.requirement_policy import RequirementPolicyRule
from app.contracts.requirement_reconciliation import RequirementReconcilerInput, RequirementSnapshot, serialize_requirement_context_snapshot
from app.models.enums import AttachmentProcessingState, EvidenceValidity, ProposalType, RequirementState
from app.services.policy.requirement_context import RequirementPolicyContextError, RequirementPolicyContextService


class FakeGetRepository:
    def __init__(self, item=None) -> None:
        self.item = item

    def get(self, _item_id):
        return self.item


class FakeListRepository:
    def __init__(self, items=()) -> None:
        self.items = items

    def list_for_project(self, _project_id):
        return self.items

    def list_for_project_for_update(self, _project_id):
        return self.items

    def list_for_correspondence_event(self, _event_id):
        return self.items


class FakeLineageRepository:
    def __init__(self, *, proposal_evidence=(), snapshot_evidence=()) -> None:
        self.proposal_evidence = proposal_evidence
        self.snapshot_evidence = snapshot_evidence

    def list_evidence_by_ids(self, _evidence_ids):
        return self.snapshot_evidence

    def list_proposal_evidence(self, _proposal_id):
        return self.proposal_evidence


def _fixture():
    project_id = uuid4()
    event_id = uuid4()
    link_id = uuid4()
    requirement_id = uuid4()
    requirement = SimpleNamespace(
        id=requirement_id,
        project_id=project_id,
        name="Provide report",
        description="Provide the final report.",
        state=RequirementState.OPEN,
        expected_date=None,
    )
    correspondence = SimpleNamespace(
        id=event_id,
        subject="Status update",
        body="The report is partly complete.",
    )
    link = SimpleNamespace(
        id=link_id,
        correspondence_event_id=event_id,
        project_id=project_id,
    )
    m11_input = RequirementReconcilerInput(
        project_id=project_id,
        authoritative_project_link_id=link_id,
        correspondence=ResolverCorrespondence(
            correspondence_event_id=event_id,
            source="fixture",
            sender_identifier="sender@example.test",
            subject=correspondence.subject,
            body=correspondence.body,
            received_at=datetime.now(UTC),
        ),
        requirements=(
            RequirementSnapshot(
                requirement_id=requirement_id,
                name=requirement.name,
                description=requirement.description,
                current_state=RequirementState.OPEN,
            ),
        ),
    )
    source_evidence = RequirementSourceEvidence(
        correspondence_event_id=event_id,
        source_field=ResolverSourceField.BODY,
        excerpt="partly complete",
    )
    reconciliation = RequirementReconciliation(
        existing_impacts=(
            ExistingRequirementImpact(
                requirement_id=requirement_id,
                disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                proposed_state=RequirementState.PARTIAL,
                evidence=(source_evidence,),
                interpretation="The report appears partly complete.",
            ),
        )
    )
    proposal = SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=event_id,
        proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        structured_output=reconciliation.model_dump(mode="json"),
        input_metadata=serialize_requirement_context_snapshot(m11_input),
    )
    return proposal, correspondence, link, requirement


def _service(*, correspondence, link, requirements, proposal_evidence=()):
    return RequirementPolicyContextService(
        correspondence_repository=FakeGetRepository(correspondence),
        project_link_repository=FakeGetRepository(link),
        requirement_repository=FakeListRepository(requirements),
        attachment_repository=FakeListRepository(),
        lineage_repository=FakeLineageRepository(
            proposal_evidence=proposal_evidence
        ),
    )


def test_reconstructs_m11_snapshot_and_preserves_current_state_for_comparison() -> None:
    proposal, correspondence, link, requirement = _fixture()
    requirement.state = RequirementState.PARTIAL
    evidence = SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=proposal.correspondence_event_id,
        attachment_id=None,
        project_id=link.project_id,
        requirement_id=requirement.id,
        source_type="body",
        excerpt="partly complete",
        page_number=None,
        section=None,
        provenance_metadata={"start_offset": 14, "end_offset": 30},
        validity=EvidenceValidity.INVALIDATED,
    )

    context = _service(
        correspondence=correspondence,
        link=link,
        requirements=(requirement,),
        proposal_evidence=(evidence,),
    ).build(proposal)

    assert context.m11_snapshot.requirements[0].current_state is RequirementState.OPEN
    assert context.current_requirements[0].state is RequirementState.PARTIAL
    assert context.proposal_evidence[0].validity is EvidenceValidity.INVALIDATED
    assert context.authoritative_project_link.link_id == link.id


def test_missing_project_link_is_preserved_for_policy_instead_of_hidden() -> None:
    proposal, correspondence, _, requirement = _fixture()

    context = _service(
        correspondence=correspondence,
        link=None,
        requirements=(requirement,),
    ).build(proposal)

    assert context.authoritative_project_link is None


def test_transactional_context_can_lock_current_requirements() -> None:
    proposal, correspondence, link, requirement = _fixture()
    requirement_repository = FakeListRepository((requirement,))
    service = RequirementPolicyContextService(
        correspondence_repository=FakeGetRepository(correspondence),
        project_link_repository=FakeGetRepository(link),
        requirement_repository=requirement_repository,
        attachment_repository=FakeListRepository(),
        lineage_repository=FakeLineageRepository(),
    )

    context = service.build(proposal, lock_current_requirements=True)

    assert context.current_requirements[0].requirement_id == requirement.id


@pytest.mark.parametrize(
    "change,expected_rule",
    [
        (
            {"proposal_type": ProposalType.PROJECT_RESOLUTION},
            RequirementPolicyRule.PROPOSAL_TYPE_INVALID,
        ),
        (
            {"structured_output": {"unexpected": True}},
            RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED,
        ),
        (
            {"input_metadata": None},
            RequirementPolicyRule.CONTEXT_SNAPSHOT_MISSING,
        ),
    ],
)
def test_reports_typed_integrity_failure(change, expected_rule) -> None:
    proposal, correspondence, link, requirement = _fixture()
    for name, value in change.items():
        setattr(proposal, name, value)
    service = _service(
        correspondence=correspondence,
        link=link,
        requirements=(requirement,),
    )

    with pytest.raises(RequirementPolicyContextError) as exc_info:
        service.build(proposal)

    assert exc_info.value.rule is expected_rule
