from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.core.config import Settings

GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)


def authorize_gmail(credentials_path: Path, token_path: Path) -> Credentials:
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            str(token_path), GMAIL_SCOPES
        )

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path), GMAIL_SCOPES
        )
        credentials = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def create_gmail_client(settings: Settings) -> Any:
    if not settings.gmail_enabled:
        raise RuntimeError("Gmail integration is disabled")

    credentials = authorize_gmail(
        settings.gmail_credentials_path,
        settings.gmail_token_path,
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)
