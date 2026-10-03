from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.ai.requirement_schemas import RequirementReconciliation
from app.contracts.requirement_policy import RequirementCurrentRecord, RequirementPolicyTransitionPreview
from app.contracts.requirement_reconciliation import RequirementContextSnapshot
from app.models.enums import EvidenceValidity, PolicyDecision


class RequirementReviewEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    attachment_id: UUID | None = None
    requirement_id: UUID | None = None
    source_type: str
    page_number: int | None = None
    section: str | None = None
    excerpt: str
    validity: EvidenceValidity
    invalidation_reason: str | None = None


class RequirementReviewHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    proposal_id: UUID
    policy_evaluation_id: UUID
    state_transition_id: UUID
    project_id: UUID
    reconciliation: RequirementReconciliation
    m11_snapshot: RequirementContextSnapshot
    current_requirements: tuple[RequirementCurrentRecord, ...]
    transition_preview: RequirementPolicyTransitionPreview
    evidence: tuple[RequirementReviewEvidence, ...] = ()

    @field_validator("evidence")
    @classmethod
    def require_unique_evidence(
        cls,
        value: tuple[RequirementReviewEvidence, ...],
    ) -> tuple[RequirementReviewEvidence, ...]:
        ids = [item.evidence_item_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("requirement review evidence must be unique")
        return value

    @model_validator(mode="after")
    def require_review_consistency(self) -> "RequirementReviewHandoff":
        if self.transition_preview.policy.decision is not PolicyDecision.REVIEW_REQUIRED:
            raise ValueError("requirement handoff requires a review policy decision")
        if self.m11_snapshot.project_id != self.project_id:
            raise ValueError("requirement handoff project does not match M11 snapshot")
        if self.m11_snapshot.correspondence_event_id != self.correspondence_event_id:
            raise ValueError("requirement handoff correspondence does not match M11 snapshot")
        if not set(self.transition_preview.evidence_ids).issubset({
            item.evidence_item_id for item in self.evidence
        }):
            raise ValueError("requirement transition evidence is missing from handoff")
        return self
