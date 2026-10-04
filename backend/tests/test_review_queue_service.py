from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ai.requirement_schemas import RequirementReconciliation
from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewDetail,
    ProjectResolutionReviewSummary,
)
from app.contracts.requirement_policy import RequirementPolicyTransitionPreview
from app.contracts.requirement_reconciliation import RequirementContextSnapshot
from app.contracts.requirement_review import RequirementReviewHandoff
from app.contracts.review_queue import (
    PROJECT_RESOLUTION_ALLOWED_ACTIONS,
    NewRequirementReviewReadDetail,
    ProjectResolutionReviewReadDetail,
    RequirementChangeReviewReadDetail,
)
from app.contracts.transition_preview import PolicyEvaluationSnapshot, TransitionState
from app.models.enums import PolicyDecision, ReviewStatus, ReviewType, TransitionDisposition
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.policy.requirement_review_handoff import (
    RequirementReviewHandoffError,
    RequirementReviewHandoffService,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryService,
)
from app.services.review_queue import (
    ReviewQueueIntegrityError,
    ReviewQueueNotFoundError,
    ReviewQueueQueryService,
)


def _review(review_type, *, status=ReviewStatus.PENDING, created_at=None):
    return SimpleNamespace(
        id=uuid4(),
        correspondence_event_id=uuid4(),
        state_transition_id=uuid4(),
        review_type=review_type,
        review_reason="Human review is required.",
        status=status,
        created_at=created_at or datetime.now(UTC),
        resolved_at=datetime.now(UTC) if status is not ReviewStatus.PENDING else None,
    )


def _handoff(correspondence_id, transition_id, policy_id):
    project_id = uuid4()
    proposal_id = uuid4()
    snapshot = RequirementContextSnapshot(
        project_id=project_id,
        authoritative_project_link_id=uuid4(),
        correspondence_event_id=correspondence_id,
        body_sha256="a" * 64,
        requirements=(),
    )
    policy = PolicyEvaluationSnapshot(
        id=policy_id,
        policy_version="requirement-policy/1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=("RID-406-NEW-REQUIREMENT",),
        reasons=("Human review is required.",),
    )
    preview = RequirementPolicyTransitionPreview(
        current_state=TransitionState(
            entity_type="requirement_reconciliation",
            entity_id=proposal_id,
            values={"project_id": str(project_id)},
        ),
        proposed_state=TransitionState(
            entity_type="requirement_reconciliation",
            entity_id=proposal_id,
            values={"project_id": str(project_id)},
        ),
        policy=policy,
        disposition=TransitionDisposition.REVIEW,
    )
    return RequirementReviewHandoff(
        correspondence_event_id=correspondence_id,
        proposal_id=proposal_id,
        policy_evaluation_id=policy_id,
        state_transition_id=transition_id,
        project_id=project_id,
        reconciliation=RequirementReconciliation(),
        m11_snapshot=snapshot,
        current_requirements=(),
        transition_preview=preview,
    )


def _service():
    reviews = MagicMock(spec=ReviewItemRepository)
    correspondence = MagicMock(spec=CorrespondenceEventRepository)
    project_query = MagicMock(spec=ProjectResolutionReviewQueryService)
    requirement_handoff = MagicMock(spec=RequirementReviewHandoffService)
    service = ReviewQueueQueryService(
        review_repository=reviews,
        correspondence_repository=correspondence,
        project_resolution_query_service=project_query,
        requirement_handoff_service=requirement_handoff,
    )
    return service, reviews, correspondence, project_query, requirement_handoff


def test_list_pending_preserves_repository_order_and_exact_capabilities() -> None:
    service, reviews, _, _, _ = _service()
    first = _review(ReviewType.PROJECT_RESOLUTION)
    second = _review(ReviewType.REQUIREMENT_CHANGE)
    third = _review(ReviewType.NEW_REQUIREMENT)
    reviews.list_pending.return_value = [first, second, third]

    result = service.list_pending()

    assert [item.review_item_id for item in result] == [
        first.id,
        second.id,
        third.id,
    ]
    assert result[0].allowed_actions == PROJECT_RESOLUTION_ALLOWED_ACTIONS
    assert result[1].allowed_actions == ()
    assert result[2].allowed_actions == ()


def test_resolved_project_review_exposes_no_actions() -> None:
    review = _review(ReviewType.PROJECT_RESOLUTION, status=ReviewStatus.APPROVED)

    assert ReviewQueueQueryService._summary(review).allowed_actions == ()


def test_project_resolution_detail_delegates_to_m10_query_service() -> None:
    service, reviews, _, project_query, requirement_handoff = _service()
    review = _review(ReviewType.PROJECT_RESOLUTION)
    reviews.get.return_value = review
    existing_detail = ProjectResolutionReviewDetail.model_construct(
        review=ProjectResolutionReviewSummary(
            review_item_id=review.id,
            correspondence_event_id=review.correspondence_event_id,
            status=review.status,
            review_reason=review.review_reason,
            created_at=review.created_at,
        )
    )
    project_query.get_detail.return_value = existing_detail

    result = service.get_detail(review.id)

    assert isinstance(result, ProjectResolutionReviewReadDetail)
    assert result.detail is existing_detail
    project_query.get_detail.assert_called_once_with(review.id)
    requirement_handoff.load.assert_not_called()


@pytest.mark.parametrize(
    ("review_type", "expected_type"),
    [
        (ReviewType.REQUIREMENT_CHANGE, RequirementChangeReviewReadDetail),
        (ReviewType.NEW_REQUIREMENT, NewRequirementReviewReadDetail),
    ],
)
def test_requirement_detail_reuses_m12_handoff(review_type, expected_type) -> None:
    service, reviews, correspondence, project_query, handoff_service = _service()
    review = _review(review_type)
    policy_id = uuid4()
    transition = SimpleNamespace(
        id=review.state_transition_id,
        policy_evaluation_id=policy_id,
    )
    handoff = _handoff(review.correspondence_event_id, transition.id, policy_id)
    reviews.get.return_value = review
    reviews.get_state_transition.return_value = transition
    handoff_service.load.return_value = handoff
    correspondence.get.return_value = SimpleNamespace(
        id=review.correspondence_event_id,
        source="gmail",
        sender_identifier="sender@example.test",
        sender_email="sender@example.test",
        sender_name="Sender",
        subject="Requirement update",
        body="Please review the proposed change.",
        received_at=datetime.now(UTC),
    )

    result = service.get_detail(review.id)

    assert isinstance(result, expected_type)
    assert result.allowed_actions == ()
    assert result.handoff is handoff
    handoff_service.load.assert_called_once_with(policy_id)
    project_query.get_detail.assert_not_called()


def test_unknown_review_fails_as_not_found() -> None:
    service, reviews, _, _, _ = _service()
    reviews.get.return_value = None

    with pytest.raises(ReviewQueueNotFoundError, match="not found"):
        service.get_detail(uuid4())


def test_broken_requirement_handoff_fails_as_integrity_error() -> None:
    service, reviews, _, _, handoff_service = _service()
    review = _review(ReviewType.REQUIREMENT_CHANGE)
    reviews.get.return_value = review
    reviews.get_state_transition.return_value = SimpleNamespace(
        id=review.state_transition_id,
        policy_evaluation_id=uuid4(),
    )
    handoff_service.load.side_effect = RequirementReviewHandoffError(
        "persisted internal reference was not found"
    )

    with pytest.raises(ReviewQueueIntegrityError, match="inconsistent"):
        service.get_detail(review.id)
