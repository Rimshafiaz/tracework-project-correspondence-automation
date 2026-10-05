from app.contracts.gmail_status import GmailIntegrationStatus, GmailStatus
from app.core.config import Settings
from app.models.enums import IngestionCursorStatus
from app.repositories.ingestion_cursor import IngestionCursorRepository


class GmailStatusService:
    def __init__(
        self,
        *,
        settings: Settings,
        cursor_repository: IngestionCursorRepository,
    ) -> None:
        self.settings = settings
        self.cursors = cursor_repository

    def load(self) -> GmailStatus:
        stored_authorization_present = self.settings.gmail_token_path.is_file()
        if not self.settings.gmail_enabled:
            return GmailStatus(
                status=GmailIntegrationStatus.DISABLED,
                configured_account_email=self.settings.gmail_account_email,
                stored_authorization_present=stored_authorization_present,
            )

        account_email = self.settings.gmail_account_email
        if not stored_authorization_present:
            return GmailStatus(
                status=GmailIntegrationStatus.AUTHORIZATION_REQUIRED,
                configured_account_email=account_email,
                stored_authorization_present=False,
            )

        cursor = self.cursors.get_read_only(
            source="gmail",
            account_identifier=account_email,
        )
        if cursor is None:
            return GmailStatus(
                status=GmailIntegrationStatus.CONFIGURED,
                configured_account_email=account_email,
                stored_authorization_present=True,
            )

        if cursor.status is IngestionCursorStatus.RESYNC_REQUIRED:
            status = GmailIntegrationStatus.RESYNC_REQUIRED
        elif (
            cursor.status is IngestionCursorStatus.ACTIVE
            and cursor.last_succeeded_at is not None
        ):
            status = GmailIntegrationStatus.ACTIVE
        else:
            status = GmailIntegrationStatus.CONFIGURED
        return GmailStatus(
            status=status,
            configured_account_email=account_email,
            stored_authorization_present=True,
            cursor_status=cursor.status,
            last_attempted_at=cursor.last_attempted_at,
            last_succeeded_at=cursor.last_succeeded_at,
        )
