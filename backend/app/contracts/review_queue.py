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
from app.contracts.document_revision import DocumentRevisionRule, RevisionOutcome
from app.models.enums import ReviewStatus, ReviewType, TransitionDisposition, TransitionStatus


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


class DocumentRevisionReviewDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    source_attachment_id: UUID
    filename: str
    project_id: UUID
    project_code: str
    project_name: str
    category: str
    document_family_key: str | None
    revision_label: str | None
    revision_normalized: str | None
    revision_order: int | None
    content_hash: str


class DocumentRevisionCurrentDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    revision_normalized: str
    revision_order: int
    content_hash: str


class DocumentRevisionReviewAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: UUID
    filename: str
    mime_type: str
    content_hash: str | None


class DocumentRevisionReviewReadDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_type: Literal[ReviewType.DOCUMENT_REVISION] = ReviewType.DOCUMENT_REVISION
    allowed_actions: tuple[ReviewAllowedAction, ...] = ()
    review: ReviewQueueSummary
    correspondence: ProjectResolutionReviewCorrespondence
    attachment: DocumentRevisionReviewAttachment
    state_transition_id: UUID
    transition_status: TransitionStatus
    disposition: TransitionDisposition
    incoming_document: DocumentRevisionReviewDocument
    current_document: DocumentRevisionCurrentDocument | None = None
    outcome: Literal[RevisionOutcome.REVIEW_REQUIRED] = RevisionOutcome.REVIEW_REQUIRED
    reasons: tuple[str, ...] = Field(min_length=1)
    policy_version: Literal["document-revision/1"] = "document-revision/1"
    triggered_rule_ids: tuple[DocumentRevisionRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_read_only_revision_review(self) -> "DocumentRevisionReviewReadDetail":
        if self.allowed_actions:
            raise ValueError("document revision reviews are read-only")
        if self.review.review_type is not ReviewType.DOCUMENT_REVISION:
            raise ValueError("document revision detail type is inconsistent")
        if self.transition_status is not TransitionStatus.PREVIEWED:
            raise ValueError("document revision review transition must be previewed")
        if self.disposition is not TransitionDisposition.REVIEW:
            raise ValueError("document revision review disposition must require review")
        if len(self.triggered_rule_ids) != len(self.reasons):
            raise ValueError("each document revision rule requires one reason")
        return self


ReviewReadDetail = Annotated[
    ProjectResolutionReviewReadDetail
    | RequirementChangeReviewReadDetail
    | NewRequirementReviewReadDetail
    | DocumentRevisionReviewReadDetail,
    Field(discriminator="review_type"),
]
