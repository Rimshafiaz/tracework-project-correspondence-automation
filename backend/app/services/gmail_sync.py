from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.adapters.gmail.history_sync import (
    GmailHistoryResyncRequired,
    collect_history_message_ids,
)
from app.adapters.gmail.initial_sync import collect_initial_message_ids
from app.adapters.gmail.message_parser import fetch_gmail_message
from app.adapters.gmail.normalizer import normalize_gmail_message
from app.models.enums import IngestionCursorStatus
from app.repositories.ingestion_cursor import IngestionCursorRepository
from app.services.correspondence_ingestion import CorrespondenceIngestionService


@dataclass(frozen=True)
class GmailSynchronizationResult:
    processed_count: int
    created_count: int
    cursor_value: str
    resync_required: bool = False


class GmailSyncService:
    def __init__(
        self,
        cursor_repository: IngestionCursorRepository,
        ingestion_service: CorrespondenceIngestionService,
    ) -> None:
        if cursor_repository.session is not ingestion_service.event_repository.session:
            raise ValueError("Gmail sync repositories must share one database session")
        self.cursor_repository = cursor_repository
        self.ingestion_service = ingestion_service

    def sync(
        self,
        gmail: Any,
        *,
        account_identifier: str,
        label_id: str,
        initial_after_epoch_seconds: int,
        occurred_at: datetime,
    ) -> GmailSynchronizationResult:
        cursor = self.cursor_repository.get(
            source="gmail",
            account_identifier=account_identifier,
            for_update=True,
        )
        if cursor is None:
            cursor = self.cursor_repository.create(
                source="gmail",
                account_identifier=account_identifier,
                sync_scope={
                    "label_id": label_id,
                    "initial_after_epoch_seconds": initial_after_epoch_seconds,
                    "eligible_history_events": ["messageAdded", "labelAdded"],
                },
            )

        if cursor.status in {
            IngestionCursorStatus.UNINITIALIZED,
            IngestionCursorStatus.RESYNC_REQUIRED,
        }:
            collected = collect_initial_message_ids(
                gmail,
                label_id=label_id,
                after_epoch_seconds=initial_after_epoch_seconds,
            )
            message_ids = collected.message_ids
            final_cursor = collected.starting_history_id
        else:
            if not cursor.cursor_value:
                raise ValueError("Active Gmail cursor has no value")
            try:
                collected_history = collect_history_message_ids(
                    gmail,
                    start_history_id=cursor.cursor_value,
                    label_id=label_id,
                )
            except GmailHistoryResyncRequired:
                self.cursor_repository.mark_resync_required(
                    cursor,
                    failure_metadata={
                        "reason": "history_id_expired",
                        "start_history_id": cursor.cursor_value,
                    },
                    occurred_at=occurred_at,
                )
                return GmailSynchronizationResult(
                    processed_count=0,
                    created_count=0,
                    cursor_value=cursor.cursor_value,
                    resync_required=True,
                )
            message_ids = collected_history.message_ids
            final_cursor = collected_history.final_history_id

        created_count = 0
        for message_id in message_ids:
            message = fetch_gmail_message(gmail, message_id)
            result = self.ingestion_service.ingest(normalize_gmail_message(message))
            created_count += result.created

        self.cursor_repository.mark_succeeded(
            cursor,
            cursor_value=final_cursor,
            occurred_at=occurred_at,
        )
        return GmailSynchronizationResult(
            processed_count=len(message_ids),
            created_count=created_count,
            cursor_value=final_cursor,
        )
