from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.contracts.project_resolution_review_queue import PROJECT_RESOLUTION_LINK_ENTITY_TYPE
from app.models.enums import ReviewStatus, ReviewType, TransitionStatus
from app.models.review_item import ReviewItem
from app.models.state_transition import StateTransition
from app.repositories.review_item import ReviewItemRepository, ReviewItemStateError


def test_list_pending_project_reviews_is_filtered_and_ordered() -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    expected = [MagicMock(spec=ReviewItem)]
    session.scalars.return_value.all.return_value = expected

    result = repository.list_pending_project_resolution()

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert len(statement._order_by_clauses) == 2


def test_get_for_update_locks_review_row() -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    expected = MagicMock(spec=ReviewItem)
    session.scalar.return_value = expected

    assert repository.get_for_update(uuid4()) is expected
    statement = session.scalar.call_args.args[0]
    assert statement._for_update_arg is not None


def test_get_state_transition_uses_primary_key_lookup() -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    transition_id = uuid4()
    expected = MagicMock(spec=StateTransition)
    session.get.return_value = expected

    assert repository.get_state_transition(transition_id) is expected
    session.get.assert_called_once_with(StateTransition, transition_id)


def test_project_resolution_transition_lookup_uses_stable_event_identity() -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    expected = MagicMock(spec=StateTransition)
    session.scalar.return_value = expected

    assert repository.get_project_resolution_transition(
        policy_evaluation_id=uuid4(),
        correspondence_event_id=uuid4(),
    ) is expected
    statement = session.scalar.call_args.args[0]
    assert len(statement._where_criteria) == 3
    assert PROJECT_RESOLUTION_LINK_ENTITY_TYPE in statement.compile().params.values()


def test_create_review_preserves_candidate_references_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    first = uuid4()
    second = uuid4()

    review = repository.create_project_resolution_review(
        correspondence_event_id=uuid4(),
        state_transition_id=uuid4(),
        review_reason="Project identity requires review.",
        candidate_project_ids=(first, second, first),
    )

    assert review.review_type is ReviewType.PROJECT_RESOLUTION
    assert review.status is ReviewStatus.PENDING
    assert [link.project_id for link in review.candidate_project_links] == [
        first,
        second,
    ]
    session.add.assert_called_once_with(review)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "review_type",
    [ReviewType.REQUIREMENT_CHANGE, ReviewType.NEW_REQUIREMENT],
)
def test_create_requirement_review_reuses_existing_queue_schema(review_type) -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)

    review = repository.create_requirement_review(
        correspondence_event_id=uuid4(),
        state_transition_id=uuid4(),
        review_type=review_type,
        review_reason="Requirement policy requires review.",
    )

    assert review.review_type is review_type
    assert review.status is ReviewStatus.PENDING
    assert review.candidate_project_links == []
    session.add.assert_called_once_with(review)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("method_name", "expected_status", "payload"),
    [
        ("mark_approved", ReviewStatus.APPROVED, None),
        (
            "mark_corrected",
            ReviewStatus.CORRECTED,
            {"selected_project_ids": [str(uuid4())]},
        ),
        ("mark_rejected", ReviewStatus.REJECTED, None),
    ],
)
def test_terminal_review_updates_match_existing_schema(
    method_name: str,
    expected_status: ReviewStatus,
    payload: dict[str, object] | None,
) -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    review = ReviewItem(
        correspondence_event_id=uuid4(),
        state_transition_id=uuid4(),
        review_type=ReviewType.PROJECT_RESOLUTION,
        review_reason="Project identity requires review.",
        status=ReviewStatus.PENDING,
    )
    resolved_at = datetime.now(UTC)
    method = getattr(repository, method_name)

    if payload is None:
        method(review, resolved_at=resolved_at)
    else:
        method(
            review,
            correction_payload=payload,
            resolved_at=resolved_at,
        )

    assert review.status is expected_status
    assert review.resolved_at == resolved_at
    assert review.correction_payload == payload
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_terminal_review_cannot_be_resolved_again() -> None:
    repository = ReviewItemRepository(MagicMock(spec=Session))
    review = ReviewItem(
        correspondence_event_id=uuid4(),
        state_transition_id=uuid4(),
        review_type=ReviewType.PROJECT_RESOLUTION,
        review_reason="Project identity requires review.",
        status=ReviewStatus.APPROVED,
        resolved_at=datetime.now(UTC),
    )

    with pytest.raises(ReviewItemStateError, match="already resolved"):
        repository.mark_rejected(review, resolved_at=datetime.now(UTC))


@pytest.mark.parametrize(
    ("method_name", "expected_status", "has_applied_at"),
    [
        ("mark_transition_applied", TransitionStatus.APPLIED, True),
        ("mark_transition_superseded", TransitionStatus.SUPERSEDED, False),
        ("mark_transition_rejected", TransitionStatus.REJECTED, False),
    ],
)
def test_transition_resolution_matches_human_decision(
    method_name: str,
    expected_status: TransitionStatus,
    has_applied_at: bool,
) -> None:
    session = MagicMock(spec=Session)
    repository = ReviewItemRepository(session)
    transition = MagicMock(spec=StateTransition)
    transition.status = TransitionStatus.PREVIEWED
    transition.applied_at = None
    method = getattr(repository, method_name)

    if has_applied_at:
        method(transition, applied_at=datetime.now(UTC))
    else:
        method(transition)

    assert transition.status is expected_status
    assert (transition.applied_at is not None) is has_applied_at
    session.flush.assert_called_once_with()
