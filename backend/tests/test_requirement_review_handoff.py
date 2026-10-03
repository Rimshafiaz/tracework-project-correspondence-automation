import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.requirement_schemas import ExistingRequirementImpact, NewRequirementProposal, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.contracts.requirement_policy import RequirementPolicyRule, RequirementTransitionEffect
from app.contracts.requirement_reconciliation import REQUIREMENT_CONTEXT_SNAPSHOT_KEY, REQUIREMENT_CONTEXT_SNAPSHOT_SCHEMA_VERSION, REQUIREMENT_CONTEXT_SNAPSHOT_VERSION_KEY, RequirementContextSnapshot, RequirementSnapshot
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType, RequirementState, TransitionDisposition
from app.services.policy.requirement_persistence import REQUIREMENT_RECONCILIATION_ENTITY_TYPE
from app.services.policy.requirement_review_handoff import RequirementReviewHandoffError, RequirementReviewHandoffService


class FakeLineageRepository:
    def __init__(self, *, new_requirement=False, decision=PolicyDecision.REVIEW_REQUIRED):
        project_id = uuid4()
        event_id = uuid4()
        requirement_id = uuid4()
        evidence_id = uuid4()
        reference = RequirementSourceEvidence(
            correspondence_event_id=event_id,
            source_field=ResolverSourceField.BODY,
            excerpt="review evidence",
        )
        if new_requirement:
            reconciliation = RequirementReconciliation(
                new_requirements=(
                    NewRequirementProposal(
                        name="Neutral new obligation",
                        evidence=(reference,),
                        interpretation="The correspondence appears to add scope.",
                    ),
                )
            )
            effects = []
        else:
            reconciliation = RequirementReconciliation(
                existing_impacts=(
                    ExistingRequirementImpact(
                        requirement_id=requirement_id,
                        disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                        proposed_state=RequirementState.SATISFIED,
                        evidence=(reference,),
                        interpretation="The correspondence appears to complete the requirement.",
                    ),
                )
            )
            effects = [
                RequirementTransitionEffect(
                    requirement_id=requirement_id,
                    observed_state=RequirementState.OPEN,
                    current_state=RequirementState.OPEN,
                    proposed_state=RequirementState.SATISFIED,
                    decision=PolicyDecision.REVIEW_REQUIRED,
                    triggered_rule_ids=(
                        RequirementPolicyRule.SATISFIED_REQUIRES_REVIEW,
                    ),
                    reasons=("Completion requires human review.",),
                    evidence_ids=(evidence_id,),
                ).model_dump(mode="json")
            ]
        snapshot = RequirementContextSnapshot(
            project_id=project_id,
            authoritative_project_link_id=uuid4(),
            correspondence_event_id=event_id,
            body_sha256=hashlib.sha256(b"review evidence").hexdigest(),
            requirements=(
                RequirementSnapshot(
                    requirement_id=requirement_id,
                    name="Neutral requirement",
                    current_state=RequirementState.OPEN,
                ),
            ),
        )
        self.proposal = SimpleNamespace(
            id=uuid4(),
            correspondence_event_id=event_id,
            proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
            structured_output=reconciliation.model_dump(mode="json"),
            input_metadata={
                REQUIREMENT_CONTEXT_SNAPSHOT_VERSION_KEY: REQUIREMENT_CONTEXT_SNAPSHOT_SCHEMA_VERSION,
                REQUIREMENT_CONTEXT_SNAPSHOT_KEY: snapshot.model_dump(mode="json"),
            },
        )
        self.evaluation = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_version="requirement-policy/1",
            decision=decision,
            triggered_rule_ids=["RID-400-SATISFIED-REQUIRES-REVIEW"],
            reasons=["Completion requires human review."],
        )
        self.transition = SimpleNamespace(
            id=uuid4(),
            ai_proposal_id=self.proposal.id,
            policy_evaluation_id=self.evaluation.id,
            affected_entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
            affected_entity_id=self.proposal.id,
            current_state={"project_id": str(project_id), "requirements": []},
            proposed_state={"project_id": str(project_id), "requirements": []},
            requirement_effects=effects,
            disposition=TransitionDisposition.REVIEW,
        )
        self.evidence = SimpleNamespace(
            id=evidence_id,
            attachment_id=None,
            requirement_id=None if new_requirement else requirement_id,
            source_type="body",
            page_number=None,
            section=None,
            excerpt="review evidence",
            validity=EvidenceValidity.VALID,
            invalidation_reason=None,
        )

    def get_policy_evaluation_by_id(self, evaluation_id):
        return self.evaluation if evaluation_id == self.evaluation.id else None

    def get_proposal(self, proposal_id):
        return self.proposal if proposal_id == self.proposal.id else None

    def get_state_transition(self, **_values):
        return self.transition

    def list_state_transition_evidence(self, transition_id):
        return [self.evidence] if transition_id == self.transition.id else []

    def list_proposal_evidence(self, _proposal_id):
        return [self.evidence]

    def list_policy_evidence(self, _evaluation_id):
        return [self.evidence]

    def list_evidence_by_ids(self, evidence_ids):
        return [self.evidence] if self.evidence.id in evidence_ids else []


class FakeRequirementRepository:
    def __init__(self, lineage):
        snapshot = lineage.proposal.input_metadata[REQUIREMENT_CONTEXT_SNAPSHOT_KEY]
        requirement = snapshot["requirements"][0]
        self.items = [
            SimpleNamespace(
                id=requirement["requirement_id"],
                project_id=snapshot["project_id"],
                name=requirement["name"],
                description=None,
                state=RequirementState.OPEN,
                expected_date=None,
            )
        ]

    def list_for_project(self, _project_id):
        return self.items


def test_reconstructs_requirement_review_from_existing_lineage() -> None:
    lineage = FakeLineageRepository()

    handoff = RequirementReviewHandoffService(
        lineage_repository=lineage,
        requirement_repository=FakeRequirementRepository(lineage),
    ).load(lineage.evaluation.id)

    assert handoff.proposal_id == lineage.proposal.id
    assert handoff.reconciliation.existing_impacts[0].interpretation
    assert handoff.current_requirements[0].state is RequirementState.OPEN
    assert handoff.transition_preview.requirement_effects[0].proposed_state is RequirementState.SATISFIED
    assert handoff.evidence[0].validity is EvidenceValidity.VALID
    assert handoff.transition_preview.policy.policy_version == "requirement-policy/1"


def test_non_review_policy_has_no_requirement_review_handoff() -> None:
    lineage = FakeLineageRepository(decision=PolicyDecision.ALLOW_AUTO_ACTION)

    with pytest.raises(RequirementReviewHandoffError, match="review-required"):
        RequirementReviewHandoffService(
            lineage_repository=lineage,
            requirement_repository=FakeRequirementRepository(lineage),
        ).load(lineage.evaluation.id)


def test_handoff_exposes_evidence_that_was_invalidated_after_m11() -> None:
    lineage = FakeLineageRepository()
    lineage.evidence.validity = EvidenceValidity.INVALIDATED
    lineage.evidence.invalidation_reason = "Source was retracted."

    handoff = RequirementReviewHandoffService(
        lineage_repository=lineage,
        requirement_repository=FakeRequirementRepository(lineage),
    ).load(lineage.evaluation.id)

    assert handoff.evidence[0].validity is EvidenceValidity.INVALIDATED
    assert handoff.evidence[0].invalidation_reason == "Source was retracted."
