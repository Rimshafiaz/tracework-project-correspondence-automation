from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.contracts.evidence_lineage import LineageAttribution


class ProjectActivityType(StrEnum):
    CORRESPONDENCE_LINKED = "CORRESPONDENCE_LINKED"
    PROJECT_RESOLUTION_REVIEW_CREATED = "PROJECT_RESOLUTION_REVIEW_CREATED"
    PROJECT_RESOLUTION_REVIEW_RESOLVED = "PROJECT_RESOLUTION_REVIEW_RESOLVED"
    REQUIREMENT_CHANGE_PROPOSED = "REQUIREMENT_CHANGE_PROPOSED"
    REQUIREMENT_CHANGE_APPLIED = "REQUIREMENT_CHANGE_APPLIED"
    REQUIREMENT_REVIEW_CREATED = "REQUIREMENT_REVIEW_CREATED"
    REQUIREMENT_REVIEW_APPROVED = "REQUIREMENT_REVIEW_APPROVED"
    REQUIREMENT_REVIEW_REJECTED = "REQUIREMENT_REVIEW_REJECTED"
    DOCUMENT_FILED = "DOCUMENT_FILED"
    DOCUMENT_REVISION_SELECTED_CURRENT = "DOCUMENT_REVISION_SELECTED_CURRENT"
    DOCUMENT_REVISION_RETAINED_HISTORICAL = "DOCUMENT_REVISION_RETAINED_HISTORICAL"
    DOCUMENT_REVISION_DUPLICATE_RECORDED = "DOCUMENT_REVISION_DUPLICATE_RECORDED"
    DOCUMENT_REVISION_REVIEW_CREATED = "DOCUMENT_REVISION_REVIEW_CREATED"
    FOLLOW_UP_BECAME_DUE = "FOLLOW_UP_BECAME_DUE"
    REPLY_DRAFT_APPROVED = "REPLY_DRAFT_APPROVED"
    REPLY_SENT = "REPLY_SENT"
    FOLLOW_UP_COMPLETED = "FOLLOW_UP_COMPLETED"
    FOLLOW_UP_CANCELLED = "FOLLOW_UP_CANCELLED"


class ProjectActivityEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    event_type: ProjectActivityType
    occurred_at: datetime
    project_id: UUID
    correspondence_event_id: UUID | None = None
    requirement_id: UUID | None = None
    summary: str
    attribution: LineageAttribution
    authenticated_operator_subject: str | None = None
    operator_supplied_actor_label: str | None = None
    proposal_id: UUID | None = None
    policy_evaluation_id: UUID | None = None
    state_transition_id: UUID | None = None
    review_item_id: UUID | None = None

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("activity summary must not be blank")
        return value


class ProjectActivity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    events: tuple[ProjectActivityEvent, ...]
