from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from google.oauth2.credentials import Credentials

from app.adapters import google_auth
from app.adapters.drive.client import DRIVE_FILE_SCOPE
from app.adapters.gmail.client import GMAIL_SCOPES


def _stored_token(path: Path, scopes: tuple[str, ...], *, expired: bool = False) -> None:
    expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        hours=-1 if expired else 1
    )
    credentials = Credentials(
        token="cached-access-token",
        refresh_token="cached-refresh-token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        scopes=scopes,
        expiry=expiry,
    )
    path.write_text(credentials.to_json(), encoding="utf-8")


def _mock_authorization(monkeypatch) -> tuple[MagicMock, MagicMock]:
    replacement = MagicMock()
    replacement.to_json.return_value = '{"token":"newly-authorized"}'
    flow = MagicMock()
    flow.run_local_server.return_value = replacement
    make_flow = MagicMock(return_value=flow)
    monkeypatch.setattr(
        google_auth.InstalledAppFlow,
        "from_client_secrets_file",
        make_flow,
    )
    return replacement, make_flow


def test_gmail_only_cached_token_requires_drive_reauthorization(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "token.json"
    _stored_token(token_path, GMAIL_SCOPES)
    replacement, make_flow = _mock_authorization(monkeypatch)
    requested = (*GMAIL_SCOPES, DRIVE_FILE_SCOPE)

    result = google_auth.authorize_google(
        tmp_path / "credentials.json", token_path, requested
    )

    assert result is replacement
    make_flow.assert_called_once_with(str(tmp_path / "credentials.json"), requested)
    assert token_path.read_text(encoding="utf-8") == '{"token":"newly-authorized"}'


def test_correctly_scoped_cached_token_is_reused_without_reauthorization(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "token.json"
    requested = (*GMAIL_SCOPES, DRIVE_FILE_SCOPE)
    _stored_token(token_path, requested)
    original_file = token_path.read_text(encoding="utf-8")
    _, make_flow = _mock_authorization(monkeypatch)

    result = google_auth.authorize_google(
        tmp_path / "credentials.json", token_path, requested
    )

    assert result.valid
    assert result.has_scopes(requested)
    assert token_path.read_text(encoding="utf-8") == original_file
    make_flow.assert_not_called()


def test_missing_token_uses_installed_app_authorization(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "token.json"
    replacement, make_flow = _mock_authorization(monkeypatch)
    requested = (*GMAIL_SCOPES, DRIVE_FILE_SCOPE)

    result = google_auth.authorize_google(
        tmp_path / "credentials.json", token_path, requested
    )

    assert result is replacement
    make_flow.assert_called_once_with(str(tmp_path / "credentials.json"), requested)
    assert token_path.read_text(encoding="utf-8") == '{"token":"newly-authorized"}'


def test_expired_correctly_scoped_token_is_refreshed(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "token.json"
    requested = (*GMAIL_SCOPES, DRIVE_FILE_SCOPE)
    _stored_token(token_path, requested, expired=True)
    _, make_flow = _mock_authorization(monkeypatch)
    refreshed = []

    def refresh(credentials: Credentials, request: object) -> None:
        refreshed.append(request)
        credentials.token = "refreshed-access-token"
        credentials.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)

    result = google_auth.authorize_google(
        tmp_path / "credentials.json", token_path, requested
    )

    assert len(refreshed) == 1
    assert result.token == "refreshed-access-token"
    assert result.has_scopes(requested)
    assert Credentials.from_authorized_user_file(str(token_path)).has_scopes(requested)
    make_flow.assert_not_called()


def test_scope_check_preserves_stored_scope_information(
    monkeypatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "token.json"
    _stored_token(token_path, GMAIL_SCOPES)
    requested = (*GMAIL_SCOPES, DRIVE_FILE_SCOPE)
    loaded_credentials = []
    original_loader = Credentials.from_authorized_user_file

    def capture_loaded(path: str) -> Credentials:
        credentials = original_loader(path)
        loaded_credentials.append(credentials)
        return credentials

    monkeypatch.setattr(
        google_auth.Credentials, "from_authorized_user_file", capture_loaded
    )
    _mock_authorization(monkeypatch)

    google_auth.authorize_google(tmp_path / "credentials.json", token_path, requested)

    assert len(loaded_credentials) == 1
    assert tuple(loaded_credentials[0].scopes) == GMAIL_SCOPES
    assert not loaded_credentials[0].has_scopes(requested)
