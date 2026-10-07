from collections.abc import Sequence
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


def authorize_google(
    credentials_path: Path,
    token_path: Path,
    scopes: Sequence[str],
) -> Credentials:
    requested_scopes = tuple(dict.fromkeys(scopes))
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            str(token_path),
        )

    scopes_available = bool(
        credentials and credentials.has_scopes(requested_scopes)
    )
    if credentials and credentials.valid and scopes_available:
        return credentials

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
        and scopes_available
    ):
        credentials.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path),
            requested_scopes,
        )
        credentials = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials
