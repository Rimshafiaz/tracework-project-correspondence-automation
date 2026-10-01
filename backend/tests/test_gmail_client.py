from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.adapters.gmail import client
from app.core.config import Settings


def test_authorize_gmail_reuses_valid_token(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    credentials = MagicMock(valid=True)
    load = MagicMock(return_value=credentials)
    monkeypatch.setattr(client.Credentials, "from_authorized_user_file", load)

    result = client.authorize_gmail(tmp_path / "credentials.json", token_path)

    assert result is credentials
    load.assert_called_once_with(str(token_path), client.GMAIL_SCOPES)


def test_authorize_gmail_refreshes_and_saves_expired_token(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    credentials = MagicMock(valid=False, expired=True, refresh_token="refresh")
    credentials.to_json.return_value = '{"token":"new"}'
    monkeypatch.setattr(
        client.Credentials,
        "from_authorized_user_file",
        MagicMock(return_value=credentials),
    )
    request = MagicMock()
    monkeypatch.setattr(client, "Request", MagicMock(return_value=request))

    client.authorize_gmail(tmp_path / "credentials.json", token_path)

    credentials.refresh.assert_called_once_with(request)
    assert token_path.read_text(encoding="utf-8") == '{"token":"new"}'


def test_authorize_gmail_runs_first_time_flow_and_saves_token(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "tokens" / "token.json"
    credentials = MagicMock()
    credentials.to_json.return_value = '{"token":"first"}'
    flow = MagicMock()
    flow.run_local_server.return_value = credentials
    make_flow = MagicMock(return_value=flow)
    monkeypatch.setattr(
        client.InstalledAppFlow, "from_client_secrets_file", make_flow
    )
    credentials_path = tmp_path / "credentials.json"

    result = client.authorize_gmail(credentials_path, token_path)

    assert result is credentials
    make_flow.assert_called_once_with(str(credentials_path), client.GMAIL_SCOPES)
    flow.run_local_server.assert_called_once_with(port=0)
    assert token_path.read_text(encoding="utf-8") == '{"token":"first"}'


def test_create_gmail_client_refuses_disabled_integration() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        gmail_enabled=False,
    )

    with pytest.raises(RuntimeError, match="disabled"):
        client.create_gmail_client(settings)


def test_create_gmail_client_builds_v1_service(monkeypatch, tmp_path: Path) -> None:
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
