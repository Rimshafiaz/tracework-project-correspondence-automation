from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.ai.schemas import ProjectResolution, ResolutionStatus
from app.contracts.project_candidate import ProjectCandidateSet
from app.contracts.transition_preview import PolicyEvaluationSnapshot


class ProjectResolutionReviewHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    proposal_id: UUID
    policy_evaluation_id: UUID
    candidate_set: ProjectCandidateSet
    resolution: ProjectResolution
    policy: PolicyEvaluationSnapshot
    proposal_evidence_ids: tuple[UUID, ...] = ()
    policy_evidence_ids: tuple[UUID, ...] = ()
    candidate_evidence_ids: tuple[UUID, ...] = ()
    valid_evidence_ids: tuple[UUID, ...] = ()
    invalidated_evidence_ids: tuple[UUID, ...] = ()

    @field_validator(
        "proposal_evidence_ids",
        "policy_evidence_ids",
        "candidate_evidence_ids",
        "valid_evidence_ids",
        "invalidated_evidence_ids",
    )
    @classmethod
    def require_unique_evidence_ids(
        cls,
        value: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("review handoff evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def require_consistent_evidence_validity(self) -> "ProjectResolutionReviewHandoff":
        if set(self.valid_evidence_ids).intersection(self.invalidated_evidence_ids):
            raise ValueError("review evidence cannot be both valid and invalidated")
        referenced = set(
            (
                *self.proposal_evidence_ids,
                *self.policy_evidence_ids,
                *self.candidate_evidence_ids,
            )
        )
        classified = set((*self.valid_evidence_ids, *self.invalidated_evidence_ids))
        if referenced != classified:
            raise ValueError("every review evidence reference requires a validity state")
        return self

    @property
    def selected_project_ids(self) -> tuple[UUID, ...]:
        return self.resolution.project_ids

    @property
    def alternative_project_ids(self) -> tuple[UUID, ...]:
        selected = set(self.resolution.project_ids)
        return tuple(
            candidate.project_id
            for candidate in self.candidate_set.candidates
            if candidate.project_id not in selected
        )

    @property
    def requires_manual_project_assignment(self) -> bool:
        return self.resolution.status is ResolutionStatus.NO_MATCH
