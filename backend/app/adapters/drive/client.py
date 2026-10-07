from io import BytesIO
import re
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from app.adapters.gmail.client import GMAIL_SCOPES
from app.adapters.google_auth import authorize_google
from app.contracts.document_filing import DriveFileRecord
from app.core.config import Settings

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveProviderError(RuntimeError):
    pass


class GoogleDriveClient:
    def __init__(self, service: Any) -> None:
        self.service = service

    def ensure_folder(
        self,
        *,
        name: str,
        parent_folder_id: str | None,
        app_properties: dict[str, str],
    ) -> str:
        existing = self._find_one(
            mime_type=DRIVE_FOLDER_MIME_TYPE,
            parent_folder_id=parent_folder_id,
            app_properties=app_properties,
        )
        if existing is not None:
            return existing["id"]
        body: dict[str, object] = {
            "name": name,
            "mimeType": DRIVE_FOLDER_MIME_TYPE,
            "appProperties": app_properties,
        }
        if parent_folder_id is not None:
            body["parents"] = [parent_folder_id]
        try:
            created = self.service.files().create(
                body=body,
                fields="id",
            ).execute()
            return str(created["id"])
        except Exception as exc:
            raise DriveProviderError("Google Drive folder creation failed") from exc

    def find_file(
        self,
        *,
        parent_folder_id: str,
        app_properties: dict[str, str],
    ) -> DriveFileRecord | None:
        item = self._find_one(
            mime_type=None,
            parent_folder_id=parent_folder_id,
            app_properties=app_properties,
        )
        if item is None:
            return None
        return DriveFileRecord(
            file_id=str(item["id"]),
            name=str(item["name"]),
            parent_folder_id=parent_folder_id,
        )

    def upload_file(
        self,
        *,
        name: str,
        mime_type: str,
        content: bytes,
        parent_folder_id: str,
        app_properties: dict[str, str],
    ) -> DriveFileRecord:
        body = {
            "name": name,
            "parents": [parent_folder_id],
            "appProperties": app_properties,
        }
        media = MediaIoBaseUpload(
            BytesIO(content),
            mimetype=mime_type,
            resumable=False,
        )
        try:
            created = self.service.files().create(
                body=body,
                media_body=media,
                fields="id,name,parents",
            ).execute()
            return DriveFileRecord(
                file_id=str(created["id"]),
                name=str(created.get("name", name)),
                parent_folder_id=parent_folder_id,
            )
        except Exception as exc:
            raise DriveProviderError("Google Drive file upload failed") from exc

    def _find_one(
        self,
        *,
        mime_type: str | None,
        parent_folder_id: str | None,
        app_properties: dict[str, str],
    ) -> dict[str, object] | None:
        clauses = ["trashed = false"]
        if mime_type is not None:
            clauses.append(f"mimeType = '{self._escape(mime_type)}'")
        if parent_folder_id is not None:
            clauses.append(f"'{self._escape(parent_folder_id)}' in parents")
        for key, value in sorted(app_properties.items()):
            clauses.append(
                "appProperties has { "
                f"key='{self._escape(key)}' and value='{self._escape(value)}'"
                " }"
            )
        try:
            response = self.service.files().list(
                q=" and ".join(clauses),
                spaces="drive",
                fields="files(id,name,parents)",
                pageSize=2,
            ).execute()
        except Exception as exc:
            raise DriveProviderError("Google Drive lookup failed") from exc
        files = response.get("files", ())
        if len(files) > 1:
            raise DriveProviderError("Google Drive lookup returned duplicate managed items")
        return files[0] if files else None

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")


def sanitize_drive_name(value: str) -> str:
    value = re.sub(r"[\x00-\x1f/\\]+", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    if not value:
        raise ValueError("Drive name becomes blank after sanitization")
    return value[:180].rstrip(" .-")


def create_drive_client(settings: Settings) -> GoogleDriveClient:
    if not settings.drive_enabled:
        raise RuntimeError("Google Drive integration is disabled")
    credentials = authorize_google(
        settings.gmail_credentials_path,
        settings.gmail_token_path,
        (*GMAIL_SCOPES, DRIVE_FILE_SCOPE),
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return GoogleDriveClient(service)
