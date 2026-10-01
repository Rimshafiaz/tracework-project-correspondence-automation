from datetime import UTC, datetime

from app.adapters.gmail.client import create_gmail_client
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.ingestion_cursor import IngestionCursorRepository
from app.services.correspondence_ingestion import CorrespondenceIngestionService
from app.services.gmail_sync import GmailSynchronizationResult, GmailSyncService


def run_gmail_sync(settings: Settings | None = None) -> GmailSynchronizationResult:
    settings = settings or get_settings()
    if not settings.gmail_enabled:
        raise RuntimeError("Gmail integration is disabled")
    if (
        settings.gmail_account_email is None
        or settings.gmail_label_id is None
        or settings.gmail_initial_after_epoch_seconds is None
    ):
        raise ValueError("Gmail configuration is incomplete")

    gmail = create_gmail_client(settings)
    with SessionLocal.begin() as session:
        ingestion_service = CorrespondenceIngestionService(
            CorrespondenceEventRepository(session),
            AttachmentRepository(session),
        )
        sync_service = GmailSyncService(
            IngestionCursorRepository(session),
            ingestion_service,
        )
        return sync_service.sync(
            gmail,
            account_identifier=settings.gmail_account_email,
            label_id=settings.gmail_label_id,
            initial_after_epoch_seconds=settings.gmail_initial_after_epoch_seconds,
            occurred_at=datetime.now(UTC),
        )


def main() -> None:
    result = run_gmail_sync()
    print(
        f"Gmail sync completed: processed={result.processed_count}, "
        f"created={result.created_count}, cursor={result.cursor_value}, "
        f"resync_required={result.resync_required}"
    )


if __name__ == "__main__":
    main()
