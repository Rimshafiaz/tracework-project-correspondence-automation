from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReviewStatus


class RequirementReviewAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RequirementReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_item_id: UUID
    status: ReviewStatus
    action: RequirementReviewAction
    applied_requirement_ids: tuple[UUID, ...] = ()
    follow_up_ids: tuple[UUID, ...] = ()
    idempotent_replay: bool
