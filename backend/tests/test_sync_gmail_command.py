from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.commands import sync_gmail
from app.core.config import Settings
from app.services.gmail_sync import GmailSynchronizationResult


def enabled_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=True,
        gmail_account_email="tracework@example.com",
        gmail_label_id="Label_123",
        gmail_initial_after_epoch_seconds=1790838000,
    )


def test_run_gmail_sync_uses_one_transaction(monkeypatch) -> None:
    settings = enabled_settings()
    gmail = MagicMock()
    monkeypatch.setattr(sync_gmail, "create_gmail_client", MagicMock(return_value=gmail))
    session = MagicMock(spec=Session)
    transaction = MagicMock()
    transaction.__enter__.return_value = session
    begin = MagicMock(return_value=transaction)
    monkeypatch.setattr(sync_gmail.SessionLocal, "begin", begin)
    expected = GmailSynchronizationResult(2, 1, "history-20")
    run = MagicMock(return_value=expected)
    monkeypatch.setattr(sync_gmail.GmailSyncService, "sync", run)

    result = sync_gmail.run_gmail_sync(settings)

    assert result is expected
    begin.assert_called_once_with()
    transaction.__enter__.assert_called_once_with()
    transaction.__exit__.assert_called_once_with(None, None, None)
    run.assert_called_once()
    gmail_arg = run.call_args.args[0]
    arguments = run.call_args.kwargs
    assert gmail_arg is gmail
    assert arguments["account_identifier"] == "tracework@example.com"
    assert arguments["label_id"] == "Label_123"
    assert arguments["initial_after_epoch_seconds"] == 1790838000
    assert arguments["occurred_at"].tzinfo is not None


def test_run_gmail_sync_rolls_back_transaction_on_failure(monkeypatch) -> None:
    settings = enabled_settings()
    monkeypatch.setattr(sync_gmail, "create_gmail_client", MagicMock())
    session = MagicMock(spec=Session)
    transaction = MagicMock()
    transaction.__enter__.return_value = session
    monkeypatch.setattr(sync_gmail.SessionLocal, "begin", MagicMock(return_value=transaction))
    error = RuntimeError("sync failed")
    monkeypatch.setattr(
        sync_gmail.GmailSyncService,
        "sync",
        MagicMock(side_effect=error),
    )

    with pytest.raises(RuntimeError, match="sync failed"):
        sync_gmail.run_gmail_sync(settings)

    exit_arguments = transaction.__exit__.call_args.args
    assert exit_arguments[0] is RuntimeError
    assert exit_arguments[1] is error


def test_run_gmail_sync_refuses_disabled_integration(monkeypatch) -> None:
    create_client = MagicMock()
    monkeypatch.setattr(sync_gmail, "create_gmail_client", create_client)
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=False,
    )

    with pytest.raises(RuntimeError, match="disabled"):
        sync_gmail.run_gmail_sync(settings)

    create_client.assert_not_called()
