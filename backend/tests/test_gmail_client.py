from unittest.mock import MagicMock

import pytest

from app.adapters.gmail import client
from app.core.config import Settings


def test_authorize_gmail_uses_shared_scope_aware_authorization(monkeypatch) -> None:
    authorize = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(client, "authorize_google", authorize)

    result = client.authorize_gmail("credentials.json", "token.json")

    assert result is authorize.return_value
    authorize.assert_called_once_with("credentials.json", "token.json", client.GMAIL_SCOPES)


def test_create_gmail_client_refuses_disabled_integration() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=False,
    )

    with pytest.raises(RuntimeError, match="disabled"):
        client.create_gmail_client(settings)


def test_create_gmail_client_builds_v1_service(monkeypatch, tmp_path) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=True,
        gmail_account_email="tracework@example.com",
        gmail_label_id="Label_123",
        gmail_initial_after_epoch_seconds=1790838000,
        gmail_credentials_path=tmp_path / "credentials.json",
        gmail_token_path=tmp_path / "token.json",
    )
    credentials = MagicMock()
    service = MagicMock()
    authorize = MagicMock(return_value=credentials)
    build = MagicMock(return_value=service)
    monkeypatch.setattr(client, "authorize_gmail", authorize)
    monkeypatch.setattr(client, "build", build)

    result = client.create_gmail_client(settings)

    assert result is service
    authorize.assert_called_once_with(
        settings.gmail_credentials_path,
        settings.gmail_token_path,
    )
    build.assert_called_once_with(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )
