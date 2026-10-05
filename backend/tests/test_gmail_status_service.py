from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.contracts.gmail_status import GmailIntegrationStatus
from app.core.config import Settings
from app.models.enums import IngestionCursorStatus
from app.models.ingestion_cursor import IngestionCursor
from app.repositories.ingestion_cursor import IngestionCursorRepository
from app.services.gmail_status import GmailStatusService


def _settings(tmp_path, *, enabled: bool = True) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://example",
        gmail_enabled=enabled,
        gmail_account_email="configured@example.com" if enabled else None,
        gmail_label_id="Label_123" if enabled else None,
        gmail_initial_after_epoch_seconds=1 if enabled else None,
        gmail_token_path=tmp_path / "token.json",
        _env_file=None,
    )


def _service(settings: Settings, cursor=None):
    repository = MagicMock(spec=IngestionCursorRepository)
    repository.get_read_only.return_value = cursor
    return GmailStatusService(settings=settings, cursor_repository=repository), repository


def test_disabled_and_missing_authorization_are_distinct(tmp_path) -> None:
    disabled, disabled_repository = _service(_settings(tmp_path, enabled=False))
    required, required_repository = _service(_settings(tmp_path))

    assert disabled.load().status is GmailIntegrationStatus.DISABLED
    assert required.load().status is GmailIntegrationStatus.AUTHORIZATION_REQUIRED
    disabled_repository.get_read_only.assert_not_called()
    required_repository.get_read_only.assert_not_called()


def test_authorization_file_alone_is_only_configured(tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.gmail_token_path.write_text("not read by status service", encoding="utf-8")
    service, repository = _service(settings)

    result = service.load()

    assert result.status is GmailIntegrationStatus.CONFIGURED
    assert result.stored_authorization_present is True
    assert result.configured_account_email == "configured@example.com"
    repository.get_read_only.assert_called_once_with(
        source="gmail",
        account_identifier="configured@example.com",
    )


def test_successful_sync_is_active_and_resync_is_distinct(tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.gmail_token_path.write_text("present", encoding="utf-8")
    now = datetime.now(UTC)
    active = IngestionCursor(
        source="gmail",
        account_identifier="configured@example.com",
        cursor_value="history-1",
        status=IngestionCursorStatus.ACTIVE,
        sync_scope={},
        last_attempted_at=now,
        last_succeeded_at=now,
    )
    resync = IngestionCursor(
        source="gmail",
        account_identifier="configured@example.com",
        cursor_value="expired",
        status=IngestionCursorStatus.RESYNC_REQUIRED,
        sync_scope={},
        last_attempted_at=now,
        last_succeeded_at=now,
    )

    active_result = _service(settings, active)[0].load()
    resync_result = _service(settings, resync)[0].load()

    assert active_result.status is GmailIntegrationStatus.ACTIVE
    assert active_result.last_succeeded_at == now
    assert resync_result.status is GmailIntegrationStatus.RESYNC_REQUIRED
