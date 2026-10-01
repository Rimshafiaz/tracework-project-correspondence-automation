from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, call

import pytest
from sqlalchemy.orm import Session

from app.adapters.gmail.history_sync import (
    GmailHistoryResyncRequired,
    GmailHistorySyncResult,
)
from app.adapters.gmail.initial_sync import GmailInitialSyncResult
from app.models.enums import IngestionCursorStatus
from app.models.ingestion_cursor import IngestionCursor
from app.repositories.ingestion_cursor import IngestionCursorRepository
from app.services import gmail_sync
from app.services.correspondence_ingestion import (
    CorrespondenceIngestionResult,
    CorrespondenceIngestionService,
)
from app.services.gmail_sync import GmailSyncService

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def make_service(cursor: IngestionCursor | None) -> tuple[GmailSyncService, MagicMock, MagicMock]:
    session = MagicMock(spec=Session)
    cursor_repository = MagicMock(spec=IngestionCursorRepository)
    cursor_repository.session = session
    cursor_repository.get.return_value = cursor
    ingestion_service = MagicMock(spec=CorrespondenceIngestionService)
    event_repository = MagicMock()
    event_repository.session = session
    ingestion_service.event_repository = event_repository
    return GmailSyncService(cursor_repository, ingestion_service), cursor_repository, ingestion_service


def test_initial_sync_persists_messages_before_advancing_cursor(monkeypatch) -> None:
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        status=IngestionCursorStatus.UNINITIALIZED,
        sync_scope={},
    )
    service, cursor_repository, ingestion_service = make_service(cursor)
    monkeypatch.setattr(
        gmail_sync,
        "collect_initial_message_ids",
        MagicMock(return_value=GmailInitialSyncResult(("one", "two"), "start-10")),
    )
    fetch = MagicMock(side_effect=["gmail-one", "gmail-two"])
    normalize = MagicMock(side_effect=["normalized-one", "normalized-two"])
    monkeypatch.setattr(gmail_sync, "fetch_gmail_message", fetch)
    monkeypatch.setattr(gmail_sync, "normalize_gmail_message", normalize)
    ingestion_service.ingest.side_effect = [
        CorrespondenceIngestionResult(MagicMock(), True),
        CorrespondenceIngestionResult(MagicMock(), False),
    ]

    result = service.sync(
        MagicMock(),
        account_identifier="account@example.com",
        label_id="Label_123",
        initial_after_epoch_seconds=1790838000,
        occurred_at=NOW,
    )

    assert result.processed_count == 2
    assert result.created_count == 1
    assert result.cursor_value == "start-10"
    assert fetch.call_args_list == [call(ANY, "one"), call(ANY, "two")]
    assert ingestion_service.ingest.call_args_list == [
        call("normalized-one"),
        call("normalized-two"),
    ]
    cursor_repository.mark_succeeded.assert_called_once_with(
        cursor,
        cursor_value="start-10",
        occurred_at=NOW,
    )


def test_first_sync_creates_cursor_with_the_approved_scope(monkeypatch) -> None:
    service, cursor_repository, _ = make_service(None)
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        status=IngestionCursorStatus.UNINITIALIZED,
        sync_scope={},
    )
    cursor_repository.create.return_value = cursor
    monkeypatch.setattr(
        gmail_sync,
        "collect_initial_message_ids",
        MagicMock(return_value=GmailInitialSyncResult((), "start-10")),
    )

    service.sync(
        MagicMock(),
        account_identifier="account@example.com",
        label_id="Label_123",
        initial_after_epoch_seconds=1790838000,
        occurred_at=NOW,
    )

    cursor_repository.get.assert_called_once_with(
        source="gmail",
        account_identifier="account@example.com",
        for_update=True,
    )
    cursor_repository.create.assert_called_once_with(
        source="gmail",
        account_identifier="account@example.com",
        sync_scope={
            "label_id": "Label_123",
            "initial_after_epoch_seconds": 1790838000,
            "eligible_history_events": ["messageAdded", "labelAdded"],
        },
    )


def test_incremental_sync_uses_history_and_final_cursor(monkeypatch) -> None:
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        cursor_value="start-10",
        status=IngestionCursorStatus.ACTIVE,
        sync_scope={},
    )
    service, cursor_repository, ingestion_service = make_service(cursor)
    collect = MagicMock(return_value=GmailHistorySyncResult(("three",), "final-20"))
    monkeypatch.setattr(gmail_sync, "collect_history_message_ids", collect)
    monkeypatch.setattr(gmail_sync, "fetch_gmail_message", MagicMock(return_value="gmail-three"))
    monkeypatch.setattr(gmail_sync, "normalize_gmail_message", MagicMock(return_value="normalized-three"))
    ingestion_service.ingest.return_value = CorrespondenceIngestionResult(MagicMock(), True)

    result = service.sync(
        MagicMock(),
        account_identifier="account@example.com",
        label_id="Label_123",
        initial_after_epoch_seconds=1790838000,
        occurred_at=NOW,
    )

    assert result.cursor_value == "final-20"
    collect.assert_called_once_with(
        ANY,
        start_history_id="start-10",
        label_id="Label_123",
    )
    cursor_repository.mark_succeeded.assert_called_once_with(
        cursor,
        cursor_value="final-20",
        occurred_at=NOW,
    )


def test_expired_history_marks_resync_without_fetching_messages(monkeypatch) -> None:
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        cursor_value="expired",
        status=IngestionCursorStatus.ACTIVE,
        sync_scope={},
    )
    service, cursor_repository, ingestion_service = make_service(cursor)
    monkeypatch.setattr(
        gmail_sync,
        "collect_history_message_ids",
        MagicMock(side_effect=GmailHistoryResyncRequired("expired")),
    )
    fetch = MagicMock()
    monkeypatch.setattr(gmail_sync, "fetch_gmail_message", fetch)

    result = service.sync(
        MagicMock(),
        account_identifier="account@example.com",
        label_id="Label_123",
        initial_after_epoch_seconds=1790838000,
        occurred_at=NOW,
    )

    assert result.resync_required is True
    cursor_repository.mark_resync_required.assert_called_once_with(
        cursor,
        failure_metadata={
            "reason": "history_id_expired",
            "start_history_id": "expired",
        },
        occurred_at=NOW,
    )
    fetch.assert_not_called()
    ingestion_service.ingest.assert_not_called()
    cursor_repository.mark_succeeded.assert_not_called()


def test_resync_required_cursor_runs_bounded_idempotent_recovery(monkeypatch) -> None:
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        cursor_value="expired",
        status=IngestionCursorStatus.RESYNC_REQUIRED,
        sync_scope={},
    )
    service, cursor_repository, ingestion_service = make_service(cursor)
    collect = MagicMock(
        return_value=GmailInitialSyncResult(("existing", "new"), "recovered-30")
    )
    monkeypatch.setattr(gmail_sync, "collect_initial_message_ids", collect)
    fetch = MagicMock(side_effect=["gmail-existing", "gmail-new"])
    normalize = MagicMock(side_effect=["normalized-existing", "normalized-new"])
    monkeypatch.setattr(gmail_sync, "fetch_gmail_message", fetch)
    monkeypatch.setattr(gmail_sync, "normalize_gmail_message", normalize)
    ingestion_service.ingest.side_effect = [
        CorrespondenceIngestionResult(MagicMock(), False),
        CorrespondenceIngestionResult(MagicMock(), True),
    ]

    result = service.sync(
        MagicMock(),
        account_identifier="account@example.com",
        label_id="Label_123",
        initial_after_epoch_seconds=1790838000,
        occurred_at=NOW,
    )

    assert result.processed_count == 2
    assert result.created_count == 1
    assert result.cursor_value == "recovered-30"
    assert result.resync_required is False
    collect.assert_called_once_with(
        ANY,
        label_id="Label_123",
        after_epoch_seconds=1790838000,
    )
    cursor_repository.mark_succeeded.assert_called_once_with(
        cursor,
        cursor_value="recovered-30",
        occurred_at=NOW,
    )


def test_failed_bounded_resync_preserves_resync_cursor(monkeypatch) -> None:
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        cursor_value="expired",
        status=IngestionCursorStatus.RESYNC_REQUIRED,
        sync_scope={},
    )
    service, cursor_repository, _ = make_service(cursor)
    monkeypatch.setattr(
        gmail_sync,
        "collect_initial_message_ids",
        MagicMock(side_effect=RuntimeError("resync failed")),
    )

    with pytest.raises(RuntimeError, match="resync failed"):
        service.sync(
            MagicMock(),
            account_identifier="account@example.com",
            label_id="Label_123",
            initial_after_epoch_seconds=1790838000,
            occurred_at=NOW,
        )

    assert cursor.status is IngestionCursorStatus.RESYNC_REQUIRED
    assert cursor.cursor_value == "expired"
    cursor_repository.mark_succeeded.assert_not_called()


def test_message_failure_does_not_advance_cursor(monkeypatch) -> None:
    cursor = IngestionCursor(
        source="gmail",
        account_identifier="account@example.com",
        cursor_value="start-10",
        status=IngestionCursorStatus.ACTIVE,
        sync_scope={},
    )
    service, cursor_repository, _ = make_service(cursor)
    monkeypatch.setattr(
        gmail_sync,
        "collect_history_message_ids",
        MagicMock(return_value=GmailHistorySyncResult(("broken",), "final-20")),
    )
    monkeypatch.setattr(
        gmail_sync,
        "fetch_gmail_message",
        MagicMock(side_effect=RuntimeError("fetch failed")),
    )

    with pytest.raises(RuntimeError, match="fetch failed"):
        service.sync(
            MagicMock(),
            account_identifier="account@example.com",
            label_id="Label_123",
            initial_after_epoch_seconds=1790838000,
            occurred_at=NOW,
        )

    cursor_repository.mark_succeeded.assert_not_called()
