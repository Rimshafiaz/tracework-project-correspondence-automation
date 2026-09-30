from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ai_proposal import AIProposal, AIProposalEvidence
from app.models.audit_event import AuditEvent
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType, ReviewStatus, ReviewType, TransitionDisposition, TransitionStatus
from app.models.evidence_item import EvidenceItem
from app.models.policy_evaluation import PolicyEvaluation, PolicyEvaluationEvidence
from app.models.review_item import ReviewItem
from app.models.state_transition import StateTransition, StateTransitionEvidence


class LineageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_evidence(
        self,
        *,
        correspondence_event_id: UUID,
        source_type: str,
        excerpt: str,
        attachment_id: UUID | None = None,
        project_id: UUID | None = None,
        requirement_id: UUID | None = None,
        page_number: int | None = None,
        section: str | None = None,
        normalized_value: str | None = None,
        provenance_metadata: dict[str, object] | None = None,
    ) -> EvidenceItem:
        evidence = EvidenceItem(
            correspondence_event_id=correspondence_event_id,
            attachment_id=attachment_id,
            project_id=project_id,
            requirement_id=requirement_id,
            source_type=source_type,
            page_number=page_number,
            section=section,
            excerpt=excerpt,
            normalized_value=normalized_value,
            provenance_metadata=provenance_metadata,
            validity=EvidenceValidity.VALID,
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence

    def create_proposal(
        self,
        *,
        correspondence_event_id: UUID,
        proposal_type: ProposalType,
        model_identifier: str,
        prompt_version: str,
        input_hash: str,
        structured_output: dict[str, object],
        evidence_item_ids: Sequence[UUID],
        input_metadata: dict[str, object] | None = None,
    ) -> AIProposal:
        proposal = AIProposal(
            correspondence_event_id=correspondence_event_id,
            proposal_type=proposal_type,
            model_identifier=model_identifier,
            prompt_version=prompt_version,
            input_hash=input_hash,
            input_metadata=input_metadata,
            structured_output=structured_output,
            evidence_links=[
                AIProposalEvidence(evidence_item_id=evidence_id)
                for evidence_id in evidence_item_ids
            ],
        )
        self.session.add(proposal)
        self.session.flush()
        return proposal

    def create_policy_evaluation(
        self,
        *,
        ai_proposal_id: UUID,
        policy_version: str,
        decision: PolicyDecision,
        triggered_rule_ids: list[str],
        reasons: list[str],
        evidence_item_ids: Sequence[UUID],
    ) -> PolicyEvaluation:
        evaluation = PolicyEvaluation(
            ai_proposal_id=ai_proposal_id,
            policy_version=policy_version,
            decision=decision,
            triggered_rule_ids=triggered_rule_ids,
            reasons=reasons,
            evidence_links=[
                PolicyEvaluationEvidence(evidence_item_id=evidence_id)
                for evidence_id in evidence_item_ids
            ],
        )
        self.session.add(evaluation)
        self.session.flush()
        return evaluation

    def create_transition(
        self,
        *,
        ai_proposal_id: UUID,
        policy_evaluation_id: UUID,
        affected_entity_type: str,
        affected_entity_id: UUID,
        current_state: dict[str, object],
        proposed_state: dict[str, object],
        requirement_effects: list[dict[str, object]],
        document_effects: list[dict[str, object]],
        follow_up_effects: list[dict[str, object]],
        disposition: TransitionDisposition,
        evidence_item_ids: Sequence[UUID],
    ) -> StateTransition:
        transition = StateTransition(
            ai_proposal_id=ai_proposal_id,
            policy_evaluation_id=policy_evaluation_id,
            affected_entity_type=affected_entity_type,
            affected_entity_id=affected_entity_id,
            current_state=current_state,
            proposed_state=proposed_state,
            requirement_effects=requirement_effects,
            document_effects=document_effects,
            follow_up_effects=follow_up_effects,
            disposition=disposition,
            status=TransitionStatus.PREVIEWED,
            evidence_links=[
                StateTransitionEvidence(evidence_item_id=evidence_id)
                for evidence_id in evidence_item_ids
            ],
        )
        self.session.add(transition)
        self.session.flush()
        return transition

    def create_review_item(
        self,
        *,
        correspondence_event_id: UUID,
        state_transition_id: UUID,
        review_type: ReviewType,
        review_reason: str,
    ) -> ReviewItem:
        review_item = ReviewItem(
            correspondence_event_id=correspondence_event_id,
            state_transition_id=state_transition_id,
            review_type=review_type,
            review_reason=review_reason,
            status=ReviewStatus.PENDING,
        )
        self.session.add(review_item)
        self.session.flush()
        return review_item

    def create_audit_event(
        self,
        *,
        event_type: str,
        actor_type: str,
        details: dict[str, object],
        actor_identifier: str | None = None,
        correspondence_event_id: UUID | None = None,
        project_id: UUID | None = None,
        requirement_id: UUID | None = None,
        ai_proposal_id: UUID | None = None,
        policy_evaluation_id: UUID | None = None,
        state_transition_id: UUID | None = None,
        review_item_id: UUID | None = None,
    ) -> AuditEvent:
        lineage_ids = (
            correspondence_event_id,
            project_id,
            requirement_id,
            ai_proposal_id,
            policy_evaluation_id,
            state_transition_id,
            review_item_id,
        )
        if not any(lineage_ids):
            raise ValueError("An audit event requires at least one lineage reference")
        audit_event = AuditEvent(
            event_type=event_type,
            actor_type=actor_type,
            actor_identifier=actor_identifier,
            details=details,
            correspondence_event_id=correspondence_event_id,
            project_id=project_id,
            requirement_id=requirement_id,
            ai_proposal_id=ai_proposal_id,
            policy_evaluation_id=policy_evaluation_id,
            state_transition_id=state_transition_id,
            review_item_id=review_item_id,
        )
        self.session.add(audit_event)
        self.session.flush()
        return audit_event
