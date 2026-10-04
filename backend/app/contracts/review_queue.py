from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewCorrespondence,
    ProjectResolutionReviewDetail,
)
from app.contracts.requirement_review import RequirementReviewHandoff
from app.models.enums import ReviewStatus, ReviewType


class ReviewAllowedAction(StrEnum):
    APPROVE = "APPROVE"
    ASSIGN_OR_CORRECT = "ASSIGN_OR_CORRECT"
    REJECT = "REJECT"


PROJECT_RESOLUTION_ALLOWED_ACTIONS = (
    ReviewAllowedAction.APPROVE,
    ReviewAllowedAction.ASSIGN_OR_CORRECT,
    ReviewAllowedAction.REJECT,
)


class ReviewQueueSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_item_id: UUID
    correspondence_event_id: UUID
    review_type: ReviewType
    status: ReviewStatus
    review_reason: str
    created_at: datetime
    resolved_at: datetime | None = None
    allowed_actions: tuple[ReviewAllowedAction, ...] = ()

    @field_validator("review_reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("review reason must not be blank")
        return value

    @model_validator(mode="after")
    def require_exact_capabilities(self) -> "ReviewQueueSummary":
        expected = (
            PROJECT_RESOLUTION_ALLOWED_ACTIONS
            if self.status is ReviewStatus.PENDING
            and self.review_type is ReviewType.PROJECT_RESOLUTION
            else ()
        )
        if self.allowed_actions != expected:
            raise ValueError("allowed review actions do not match review capability")
        return self


class ProjectResolutionReviewReadDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_type: Literal[ReviewType.PROJECT_RESOLUTION] = (
        ReviewType.PROJECT_RESOLUTION
    )
    allowed_actions: tuple[ReviewAllowedAction, ...]
    detail: ProjectResolutionReviewDetail

    @model_validator(mode="after")
    def require_exact_capabilities(self) -> "ProjectResolutionReviewReadDetail":
        expected = (
            PROJECT_RESOLUTION_ALLOWED_ACTIONS
            if self.detail.review.status is ReviewStatus.PENDING
            else ()
        )
        if self.allowed_actions != expected:
            raise ValueError("project-resolution detail actions are invalid")
        return self


class _RequirementReviewReadDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_actions: tuple[ReviewAllowedAction, ...] = ()
    review: ReviewQueueSummary
    correspondence: ProjectResolutionReviewCorrespondence
    handoff: RequirementReviewHandoff

    @model_validator(mode="after")
    def require_read_only_consistency(self) -> "_RequirementReviewReadDetail":
        if self.allowed_actions:
            raise ValueError("requirement reviews are read-only")
        if self.review.review_type not in {
            ReviewType.REQUIREMENT_CHANGE,
            ReviewType.NEW_REQUIREMENT,
        }:
            raise ValueError("requirement review detail has an invalid review type")
        if (
            self.review.correspondence_event_id
            != self.correspondence.correspondence_event_id
            or self.review.correspondence_event_id
            != self.handoff.correspondence_event_id
        ):
            raise ValueError("requirement review correspondence is inconsistent")
        return self


class RequirementChangeReviewReadDetail(_RequirementReviewReadDetail):
    review_type: Literal[ReviewType.REQUIREMENT_CHANGE] = (
        ReviewType.REQUIREMENT_CHANGE
    )

    @model_validator(mode="after")
    def require_matching_type(self) -> "RequirementChangeReviewReadDetail":
        if self.review.review_type is not ReviewType.REQUIREMENT_CHANGE:
            raise ValueError("requirement-change detail type is inconsistent")
        return self


class NewRequirementReviewReadDetail(_RequirementReviewReadDetail):
    review_type: Literal[ReviewType.NEW_REQUIREMENT] = ReviewType.NEW_REQUIREMENT

    @model_validator(mode="after")
    def require_matching_type(self) -> "NewRequirementReviewReadDetail":
        if self.review.review_type is not ReviewType.NEW_REQUIREMENT:
            raise ValueError("new-requirement detail type is inconsistent")
        return self


ReviewReadDetail = Annotated[
    ProjectResolutionReviewReadDetail
    | RequirementChangeReviewReadDetail
    | NewRequirementReviewReadDetail,
    Field(discriminator="review_type"),
]
