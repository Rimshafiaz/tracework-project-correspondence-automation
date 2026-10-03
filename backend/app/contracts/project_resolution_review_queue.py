from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.schemas import ProjectResolution, ResolutionStatus
from app.contracts.project_candidate import ProjectCandidateSet
from app.contracts.transition_preview import PolicyEvaluationSnapshot
from app.models.enums import EvidenceValidity, PolicyDecision, ReviewStatus, TransitionDisposition

PROJECT_RESOLUTION_LINK_ENTITY_TYPE = "correspondence_project_links"


class ProjectResolutionReviewAction(StrEnum):
    APPROVE_PROPOSAL = "APPROVE_PROPOSAL"
    CORRECT_PROJECTS = "CORRECT_PROJECTS"
    MANUAL_ASSIGNMENT = "MANUAL_ASSIGNMENT"
    REJECT = "REJECT"


class ReviewActor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_type: str
    actor_identifier: str

    @field_validator("actor_type", "actor_identifier")
    @classmethod
    def reject_blank_actor_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("review actor values must not be blank")
        return value


class ProjectResolutionReviewDecisionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: ReviewActor
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def normalize_optional_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ProjectResolutionReviewApproval(ProjectResolutionReviewDecisionContext):
    pass


class ProjectResolutionReviewReplacementAssignment(
    ProjectResolutionReviewDecisionContext
):
    project_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("project_ids")
    @classmethod
    def require_unique_projects(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("assigned project IDs must be unique")
        return value


class ProjectResolutionReviewOperatorRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_identifier: str
    comment: str | None = None

    @field_validator("actor_identifier")
    @classmethod
    def reject_blank_operator_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("operator audit label must not be blank")
        return value

    @field_validator("comment")
    @classmethod
    def normalize_request_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ProjectResolutionReviewAssignmentRequest(
    ProjectResolutionReviewOperatorRequest
):
    project_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("project_ids")
    @classmethod
    def require_unique_request_projects(
        cls,
        value: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("assigned project IDs must be unique")
        return value


class ProjectResolutionReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_item_id: UUID
    status: ReviewStatus
    action: ProjectResolutionReviewAction
    project_ids: tuple[UUID, ...] = ()
    project_link_ids: tuple[UUID, ...] = ()
    idempotent_replay: bool


class ProjectResolutionReviewSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_item_id: UUID
    correspondence_event_id: UUID
    status: ReviewStatus
    review_reason: str
    created_at: datetime
    resolved_at: datetime | None = None

    @field_validator("created_at", "resolved_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("review timestamps must include a timezone")
        return value


class ProjectResolutionReviewPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    resolver_status: ResolutionStatus
    current_project_ids: tuple[UUID, ...] = ()
    proposed_project_ids: tuple[UUID, ...] = ()
    alternative_project_ids: tuple[UUID, ...] = ()
    valid_evidence_ids: tuple[UUID, ...] = ()
    invalidated_evidence_ids: tuple[UUID, ...] = ()
    policy: PolicyEvaluationSnapshot
    disposition: TransitionDisposition
    requires_manual_project_assignment: bool

    @field_validator(
        "current_project_ids",
        "proposed_project_ids",
        "alternative_project_ids",
        "valid_evidence_ids",
        "invalidated_evidence_ids",
    )
    @classmethod
    def require_unique_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("review preview IDs must be unique")
        return value

    @model_validator(mode="after")
    def require_review_semantics(self) -> "ProjectResolutionReviewPreview":
        if self.policy.decision is not PolicyDecision.REVIEW_REQUIRED:
            raise ValueError("a review preview requires a review-required policy decision")
        if self.disposition is not TransitionDisposition.REVIEW:
            raise ValueError("a project-resolution review preview must remain in review")
        if set(self.proposed_project_ids).intersection(self.alternative_project_ids):
            raise ValueError("proposed and alternative projects must be distinct")
        if set(self.valid_evidence_ids).intersection(self.invalidated_evidence_ids):
            raise ValueError("review evidence cannot be both valid and invalidated")
        if self.resolver_status is ResolutionStatus.NO_MATCH:
            if self.proposed_project_ids or not self.requires_manual_project_assignment:
                raise ValueError("NO_MATCH requires manual assignment and no proposed project")
        elif self.requires_manual_project_assignment:
            raise ValueError("manual assignment is reserved for NO_MATCH")
        return self


class ProjectLinkAuthorizationPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    current_project_ids: tuple[UUID, ...] = ()
    authorized_project_ids: tuple[UUID, ...] = Field(min_length=1)
    added_project_ids: tuple[UUID, ...] = Field(min_length=1)
    result_project_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = ()
    policy: PolicyEvaluationSnapshot
    disposition: TransitionDisposition = TransitionDisposition.AUTO_APPLY

    @field_validator(
        "current_project_ids",
        "authorized_project_ids",
        "added_project_ids",
        "result_project_ids",
        "evidence_ids",
    )
    @classmethod
    def require_unique_authorization_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("project-link authorization IDs must be unique")
        return value

    @model_validator(mode="after")
    def require_actual_additions(self) -> "ProjectLinkAuthorizationPreview":
        current = set(self.current_project_ids)
        authorized = set(self.authorized_project_ids)
        added = set(self.added_project_ids)
        if self.policy.decision is not PolicyDecision.ALLOW_AUTO_ACTION:
            raise ValueError("automatic project links require an allow policy decision")
        if self.disposition is not TransitionDisposition.AUTO_APPLY:
            raise ValueError("automatic project links require AUTO_APPLY")
        if added != authorized - current:
            raise ValueError("added projects must be authorized projects not already linked")
        if set(self.result_project_ids) != current | added:
            raise ValueError("result projects must preserve current links and add new links")
        return self


class ProjectResolutionReviewCorrespondence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correspondence_event_id: UUID
    source: str
    sender_identifier: str
    sender_email: str | None = None
    sender_name: str | None = None
    subject: str | None = None
    body: str
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def require_received_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("correspondence timestamp must include a timezone")
        return value


class ProjectResolutionReviewEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_item_id: UUID
    attachment_id: UUID | None = None
    source_type: str
    page_number: int | None = None
    section: str | None = None
    excerpt: str
    validity: EvidenceValidity
    invalidation_reason: str | None = None


class ProjectResolutionReviewDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review: ProjectResolutionReviewSummary
    state_transition_id: UUID
    proposal_id: UUID
    policy_evaluation_id: UUID
    correspondence: ProjectResolutionReviewCorrespondence
    preview: ProjectResolutionReviewPreview
    candidate_set: ProjectCandidateSet
    resolution: ProjectResolution
    evidence: tuple[ProjectResolutionReviewEvidence, ...] = ()
