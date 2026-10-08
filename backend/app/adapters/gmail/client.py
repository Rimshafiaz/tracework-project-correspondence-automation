from typing import Any

from googleapiclient.discovery import build

from app.adapters.google_auth import authorize_google
from app.core.config import Settings

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE)


def authorize_gmail(credentials_path, token_path):
    """Authorize Gmail with the complete, narrowly scoped Gmail capability set."""
    return authorize_google(credentials_path, token_path, GMAIL_SCOPES)


def create_gmail_client(settings: Settings) -> Any:
    if not settings.gmail_enabled:
        raise RuntimeError("Gmail integration is disabled")

    credentials = authorize_gmail(
        settings.gmail_credentials_path,
        settings.gmail_token_path,
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)
