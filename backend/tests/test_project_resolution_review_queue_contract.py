from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewApproval,
    ProjectResolutionReviewDecisionContext,
    ProjectResolutionReviewReplacementAssignment,
    ProjectResolutionReviewSummary,
    ReviewActor,
)
from app.models.enums import ReviewStatus


def test_actor_records_identity_provenance_without_claiming_authentication() -> None:
    actor = ReviewActor(
        actor_type="operator_supplied",
        actor_identifier="reviewer@example.test",
    )

    assert actor.actor_type == "operator_supplied"
    assert actor.actor_identifier == "reviewer@example.test"


def test_decision_context_normalizes_optional_comment() -> None:
    actor = ReviewActor(actor_type="operator_supplied", actor_identifier="reviewer")

    assert ProjectResolutionReviewDecisionContext(
        actor=actor,
        comment="  checked source records  ",
    ).comment == "checked source records"
    assert ProjectResolutionReviewDecisionContext(
        actor=actor,
        comment="   ",
    ).comment is None


def test_approval_does_not_accept_a_replacement_project_set() -> None:
    actor = ReviewActor(actor_type="operator_supplied", actor_identifier="reviewer")

    assert ProjectResolutionReviewApproval(actor=actor).actor == actor
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectResolutionReviewApproval(actor=actor, project_ids=(uuid4(),))


def test_replacement_assignment_requires_a_nonempty_unique_project_set() -> None:
    actor = ReviewActor(actor_type="operator_supplied", actor_identifier="reviewer")
    project_id = uuid4()

    assignment = ProjectResolutionReviewReplacementAssignment(
        actor=actor,
        project_ids=(project_id,),
    )

    assert assignment.project_ids == (project_id,)
    with pytest.raises(ValidationError):
        ProjectResolutionReviewReplacementAssignment(actor=actor, project_ids=())
    with pytest.raises(ValidationError, match="must be unique"):
        ProjectResolutionReviewReplacementAssignment(
            actor=actor,
            project_ids=(project_id, project_id),
        )


def test_review_summary_requires_timezone_aware_timestamps() -> None:
    values = {
        "review_item_id": uuid4(),
        "correspondence_event_id": uuid4(),
        "status": ReviewStatus.PENDING,
        "review_reason": "Project identity requires review.",
        "created_at": datetime.now(UTC),
    }

    assert ProjectResolutionReviewSummary(**values).status is ReviewStatus.PENDING
    values["created_at"] = datetime.now()
    with pytest.raises(ValidationError, match="timezone"):
        ProjectResolutionReviewSummary(**values)
