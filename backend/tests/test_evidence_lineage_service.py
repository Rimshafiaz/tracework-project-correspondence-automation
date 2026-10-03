from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.evidence_lineage import LineageAttribution, LineageCompleteness
from app.contracts.requirement_policy import RequirementPolicyRule
from app.models.enums import (
    EvidenceValidity,
    PolicyDecision,
    ProposalType,
    RequirementState,
    ReviewStatus,
    ReviewType,
    TransitionDisposition,
    TransitionStatus,
)
from app.services.evidence_lineage import EvidenceLineageError, EvidenceLineageService


def _service_fixture(*, with_review: bool = False, with_audits: bool = True):
    now = datetime.now(UTC)
    correspondence_id = uuid4()
    proposal_id = uuid4()
    evaluation_id = uuid4()
    transition_id = uuid4()
    requirement_id = uuid4()
    project_id = uuid4()
    evidence_id = uuid4()
    attachment_id = uuid4()
    effect = {
        "requirement_id": str(requirement_id),
        "observed_state": "OPEN",
        "observed_expected_date": None,
        "current_state": "OPEN",
        "current_expected_date": None,
        "proposed_state": "PARTIAL",
        "proposed_expected_date": None,
        "decision": "ALLOW_AUTO_ACTION",
        "triggered_rule_ids": [RequirementPolicyRule.OPEN_TO_PARTIAL.value],
        "reasons": ["The low-risk transition is eligible."],
        "evidence_ids": [str(evidence_id)],
    }
    transition = SimpleNamespace(
        id=transition_id,
        ai_proposal_id=proposal_id,
        policy_evaluation_id=evaluation_id,
        affected_entity_type="requirement_reconciliation",
        affected_entity_id=proposal_id,
        current_state={"project_id": str(project_id)},
        proposed_state={"project_id": str(project_id)},
        requirement_effects=[effect],
        disposition=TransitionDisposition.AUTO_APPLY,
        status=TransitionStatus.APPLIED,
        created_at=now,
        applied_at=now + timedelta(seconds=2),
    )
    proposal = SimpleNamespace(
        id=proposal_id,
        correspondence_event_id=correspondence_id,
        proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        model_identifier="test-model",
        prompt_version="requirement-reconciler/1",
        input_hash="hash",
        structured_output={"impacts": []},
        created_at=now - timedelta(seconds=2),
    )
    evaluation = SimpleNamespace(
        id=evaluation_id,
        ai_proposal_id=proposal_id,
        policy_version="requirement-policy/1",
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=[RequirementPolicyRule.OPEN_TO_PARTIAL.value],
        reasons=["The proposal met the automatic policy."],
        evaluated_at=now,
    )
    correspondence = SimpleNamespace(
        id=correspondence_id,
        source="gmail",
        sender_identifier="sender@example.test",
        subject="Status update",
        body="The first part is complete.",
        received_at=now - timedelta(minutes=1),
    )
    evidence = SimpleNamespace(
        id=evidence_id,
        correspondence_event_id=correspondence_id,
        attachment_id=attachment_id,
        project_id=project_id,
        requirement_id=requirement_id,
        source_type="attachment_text",
        excerpt="The first part is complete.",
        provenance_metadata={"start_offset": 0, "end_offset": 27},
        page_number=1,
        section=None,
        validity=EvidenceValidity.INVALIDATED,
        invalidated_at=now + timedelta(days=1),
        invalidation_reason="A later correction retracted this evidence.",
    )
    attachment = SimpleNamespace(
        id=attachment_id,
        filename="status.pdf",
        mime_type="application/pdf",
        content_hash="abc123",
    )
    review = (
        SimpleNamespace(
            id=uuid4(),
            review_type=ReviewType.REQUIREMENT_CHANGE,
            status=ReviewStatus.APPROVED,
            review_reason="Human review was required.",
            correction_payload=None,
            created_at=now,
            resolved_at=now + timedelta(seconds=3),
        )
        if with_review
        else None
    )
    audit = SimpleNamespace(
        id=uuid4(),
        event_type="requirement_policy_auto_applied",
        actor_type="human_operator" if with_review else "system",
        actor_identifier="reviewer-label" if with_review else None,
        details={"authorization": "HUMAN_REVIEW" if with_review else "AUTO_POLICY"},
        occurred_at=now + timedelta(seconds=3),
    )
    requirement = SimpleNamespace(
        id=requirement_id,
        project_id=project_id,
        state=RequirementState.SATISFIED,
        expected_date=date(2030, 1, 5),
    )

    lineage = MagicMock()
    lineage.get_state_transition_by_id.return_value = transition
    lineage.get_proposal.return_value = proposal
    lineage.get_policy_evaluation_by_id.return_value = evaluation
    lineage.list_proposal_evidence.return_value = [evidence]
    lineage.list_policy_evidence.return_value = [evidence]
    lineage.list_state_transition_evidence.return_value = [evidence]
    lineage.list_audit_events_for_lineage.return_value = [audit] if with_audits else []
    correspondence_repository = MagicMock()
    correspondence_repository.get.return_value = correspondence
    attachment_repository = MagicMock()
    attachment_repository.list_for_correspondence_event.return_value = [attachment]
    project_links = MagicMock()
    project_links.list_approved_project_ids_for_event.return_value = [project_id]
    requirements = MagicMock()
    requirements.get.return_value = requirement
    reviews = MagicMock()
    reviews.get_by_state_transition.return_value = review
    service = EvidenceLineageService(
        lineage_repository=lineage,
        correspondence_repository=correspondence_repository,
        attachment_repository=attachment_repository,
        project_link_repository=project_links,
        requirement_repository=requirements,
        review_repository=reviews,
    )
    return service, transition_id, attachment_repository


def test_lineage_keeps_historical_and_current_facts_separate() -> None:
    service, transition_id, _ = _service_fixture()

    result = service.load(transition_id)

    assert result.completeness is LineageCompleteness.COMPLETE
    assert result.evidence[0].validity_at_proposal is EvidenceValidity.VALID
    assert result.evidence[0].validity_at_policy is EvidenceValidity.VALID
    assert result.evidence[0].validity_at_outcome is EvidenceValidity.VALID
    assert result.evidence[0].current_validity is EvidenceValidity.INVALIDATED
    assert result.transition.requirement_effects[0].current_state is RequirementState.OPEN
    assert result.current_state.requirements[0].state is RequirementState.SATISFIED
    assert result.historical_outcome.attribution is LineageAttribution.AUTOMATIC
    assert result.policy.policy_version == "requirement-policy/1"


def test_lineage_exposes_human_operator_label_without_claiming_authentication() -> None:
    service, transition_id, _ = _service_fixture(with_review=True)

    result = service.load(transition_id)

    assert result.historical_outcome.attribution is LineageAttribution.HUMAN
    assert result.historical_outcome.operator_supplied_actor_label == "reviewer-label"
    assert result.audit_events[0].operator_supplied_actor_label == "reviewer-label"


def test_lineage_marks_missing_legacy_audit_as_partial() -> None:
    service, transition_id, _ = _service_fixture(with_audits=False)

    result = service.load(transition_id)

    assert result.completeness is LineageCompleteness.LEGACY_PARTIAL
    assert result.completeness_notes


def test_lineage_fails_when_referenced_attachment_is_missing() -> None:
    service, transition_id, attachment_repository = _service_fixture()
    attachment_repository.list_for_correspondence_event.return_value = []

    with pytest.raises(EvidenceLineageError, match="attachment was not found"):
        service.load(transition_id)


def test_lineage_fails_instead_of_inventing_malformed_transition_history() -> None:
    service, transition_id, _ = _service_fixture()
    transition = service.lineage_repository.get_state_transition_by_id.return_value
    transition.requirement_effects[0]["requirement_id"] = "not-a-uuid"

    with pytest.raises(EvidenceLineageError, match="effects are invalid"):
        service.load(transition_id)
