from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import FollowUpPurpose, FollowUpStatus


class DueFollowUpContext(BaseModel):
    """Persisted, authoritative context for a DUE follow-up."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    follow_up_id: UUID
    project_id: UUID
    requirement_id: UUID
    purpose: FollowUpPurpose
    reason: str
    status: FollowUpStatus
    expected_date: date
    due_on: date
    became_due_at: datetime
    originating_state_transition_id: UUID | None
    originating_audit_event_id: UUID | None
