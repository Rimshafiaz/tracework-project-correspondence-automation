from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType, ReviewStatus, ReviewType, TransitionDisposition, TransitionStatus
from app.repositories.lineage import LineageRepository


def test_create_evidence_preserves_exact_source_details() -> None:
    session = MagicMock(spec=Session)
    repository = LineageRepository(session)
    event_id = uuid4()
    attachment_id = uuid4()

    evidence = repository.create_evidence(
        correspondence_event_id=event_id,
        attachment_id=attachment_id,
        source_type="attachment_text",
        page_number=3,
        section="Deployment",
        excerpt="The release was approved.",
        provenance_metadata={"parser": "pdf"},
    )

    assert evidence.correspondence_event_id == event_id
    assert evidence.attachment_id == attachment_id
    assert evidence.page_number == 3
    assert evidence.validity is EvidenceValidity.VALID
    session.flush.assert_called_once_with()


def test_proposal_and_policy_evaluation_link_their_evidence() -> None:
    session = MagicMock(spec=Session)
    repository = LineageRepository(session)
    evidence_ids = [uuid4(), uuid4()]

    proposal = repository.create_proposal(
        correspondence_event_id=uuid4(),
        proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        model_identifier="model-name",
        prompt_version="v1",
        input_hash="hash",
        structured_output={"state": "SATISFIED"},
        evidence_item_ids=evidence_ids,
    )
    evaluation = repository.create_policy_evaluation(
        ai_proposal_id=uuid4(),
        policy_version="v1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=["ambiguous-evidence"],
        reasons=["Evidence requires review"],
        evidence_item_ids=evidence_ids,
    )

    assert [link.evidence_item_id for link in proposal.evidence_links] == evidence_ids
    assert [link.evidence_item_id for link in evaluation.evidence_links] == evidence_ids
    assert session.flush.call_count == 2


def test_transition_and_review_start_in_preview_states() -> None:
    session = MagicMock(spec=Session)
    repository = LineageRepository(session)
    evidence_id = uuid4()

    transition = repository.create_transition(
        ai_proposal_id=uuid4(),
        policy_evaluation_id=uuid4(),
        affected_entity_type="requirement",
        affected_entity_id=uuid4(),
        current_state={"state": "OPEN"},
        proposed_state={"state": "PARTIAL"},
        requirement_effects=[],
        document_effects=[],
        follow_up_effects=[],
        disposition=TransitionDisposition.REVIEW,
        evidence_item_ids=[evidence_id],
    )
    review = repository.create_review_item(
        correspondence_event_id=uuid4(),
        state_transition_id=uuid4(),
        review_type=ReviewType.REQUIREMENT_CHANGE,
        review_reason="Policy requires review",
    )

    assert transition.status is TransitionStatus.PREVIEWED
    assert transition.evidence_links[0].evidence_item_id == evidence_id
    assert review.status is ReviewStatus.PENDING


def test_audit_event_requires_and_preserves_lineage() -> None:
    session = MagicMock(spec=Session)
    repository = LineageRepository(session)
    transition_id = uuid4()

    event = repository.create_audit_event(
        event_type="transition_previewed",
        actor_type="system",
        details={"result": "review"},
        state_transition_id=transition_id,
    )

    assert event.state_transition_id == transition_id
    with pytest.raises(ValueError, match="lineage reference"):
        repository.create_audit_event(
            event_type="orphaned",
            actor_type="system",
            details={},
        )
    assert session.add.call_count == 1
