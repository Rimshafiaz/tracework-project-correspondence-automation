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
