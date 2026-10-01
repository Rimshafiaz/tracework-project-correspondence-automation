from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.models.enums import IngestionCursorStatus
from app.models.ingestion_cursor import IngestionCursor
from app.repositories.ingestion_cursor import IngestionCursorRepository


def test_create_starts_with_no_cursor_and_does_not_commit() -> None:
    session = MagicMock(spec=Session)
    repository = IngestionCursorRepository(session)
    scope = {
        "label_id": "tracework-label",
        "initial_after_epoch_seconds": 1790838000,
        "eligible_history_events": ["messageAdded", "labelAdded"],
    }

    cursor = repository.create(
        source="gmail",
        account_identifier="account@example.com",
        sync_scope=scope,
    )

    assert cursor.status is IngestionCursorStatus.UNINITIALIZED
    assert cursor.cursor_value is None
    assert cursor.sync_scope == scope
    session.add.assert_called_once_with(cursor)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_get_can_lock_cursor_for_concurrent_polling() -> None:
    session = MagicMock(spec=Session)
    repository = IngestionCursorRepository(session)

    repository.get(
        source="gmail",
        account_identifier="account@example.com",
        for_update=True,
    )

    statement = session.scalar.call_args.args[0]
    assert len(statement._where_criteria) == 2
    assert statement._for_update_arg is not None


def test_mark_succeeded_uses_the_supplied_final_cursor() -> None:
    session = MagicMock(spec=Session)
    repository = IngestionCursorRepository(session)
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        status=IngestionCursorStatus.UNINITIALIZED,
        sync_scope={},
    )
    occurred_at = datetime(2026, 10, 1, tzinfo=UTC)

    repository.mark_succeeded(
        cursor,
        cursor_value="final-page-history-id",
        occurred_at=occurred_at,
    )

    assert cursor.cursor_value == "final-page-history-id"
    assert cursor.status is IngestionCursorStatus.ACTIVE
    assert cursor.last_attempted_at == occurred_at
    assert cursor.last_succeeded_at == occurred_at
    assert cursor.failure_metadata is None
    session.commit.assert_not_called()


def test_expired_cursor_is_preserved_for_resync() -> None:
    session = MagicMock(spec=Session)
    repository = IngestionCursorRepository(session)
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        cursor_value="expired-history-id",
        status=IngestionCursorStatus.ACTIVE,
        sync_scope={},
    )
    occurred_at = datetime(2026, 10, 1, tzinfo=UTC)

    repository.mark_resync_required(
        cursor,
        failure_metadata={"reason": "history_id_expired"},
        occurred_at=occurred_at,
    )

    assert cursor.cursor_value == "expired-history-id"
    assert cursor.status is IngestionCursorStatus.RESYNC_REQUIRED
    assert cursor.failure_metadata == {"reason": "history_id_expired"}
    session.commit.assert_not_called()
