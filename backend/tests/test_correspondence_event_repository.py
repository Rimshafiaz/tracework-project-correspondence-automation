from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import CorrespondenceProcessingState
from app.repositories.correspondence_event import CorrespondenceEventRepository


def test_create_adds_and_flushes_pending_event_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceEventRepository(session)
    received_at = datetime(2026, 10, 1, tzinfo=UTC)

    event = repository.create(
        source="email_provider",
        external_event_id="event-1",
        sender_identifier="sender@example.com",
        body="Project update",
        received_at=received_at,
    )

    assert event.source == "email_provider"
    assert event.processing_state is CorrespondenceProcessingState.PENDING
    session.add.assert_called_once_with(event)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_get_by_external_identity_uses_source_and_event_id() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceEventRepository(session)
    expected = MagicMock(spec=CorrespondenceEvent)
    session.scalar.return_value = expected

    result = repository.get_by_external_identity(
        source="email_provider",
        external_event_id="event-1",
    )

    assert result is expected
    statement = session.scalar.call_args.args[0]
    assert len(statement._where_criteria) == 2


def test_list_for_conversation_is_source_scoped() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceEventRepository(session)
    expected = [MagicMock(spec=CorrespondenceEvent)]
    session.scalars.return_value.all.return_value = expected

    result = repository.list_for_conversation(
        source="email_provider",
        external_conversation_id="conversation-1",
    )

    assert result == expected
    statement = session.scalars.call_args.args[0]
    assert len(statement._where_criteria) == 2


def test_update_processing_state_records_failure_without_committing() -> None:
    session = MagicMock(spec=Session)
    repository = CorrespondenceEventRepository(session)
    event = CorrespondenceEvent(
        id=uuid4(),
        source="email_provider",
        external_event_id="event-1",
        sender_identifier="sender@example.com",
        body="Project update",
        received_at=datetime(2026, 10, 1, tzinfo=UTC),
        processing_state=CorrespondenceProcessingState.PROCESSING,
    )
    failure = {"reason": "temporary provider error"}

    result = repository.update_processing_state(
        event,
        state=CorrespondenceProcessingState.RETRYABLE_FAILURE,
        failure_metadata=failure,
    )

    assert result is event
    assert event.processing_state is CorrespondenceProcessingState.RETRYABLE_FAILURE
    assert event.failure_metadata == failure
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()
