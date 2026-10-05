from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import IngestionCursorStatus
from app.models.ingestion_cursor import IngestionCursor


class IngestionCursorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        source: str,
        account_identifier: str,
        sync_scope: dict[str, object],
    ) -> IngestionCursor:
        cursor = IngestionCursor(
            source=source,
            account_identifier=account_identifier,
            status=IngestionCursorStatus.UNINITIALIZED,
            sync_scope=sync_scope,
        )
        self.session.add(cursor)
        self.session.flush()
        return cursor

    def get(
        self,
        *,
        source: str,
        account_identifier: str,
        for_update: bool = False,
    ) -> IngestionCursor | None:
        statement = select(IngestionCursor).where(
            IngestionCursor.source == source,
            IngestionCursor.account_identifier == account_identifier,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_read_only(
        self,
        *,
        source: str,
        account_identifier: str,
    ) -> IngestionCursor | None:
        return self.get(
            source=source,
            account_identifier=account_identifier,
            for_update=False,
        )

    def mark_succeeded(
        self,
        cursor: IngestionCursor,
        *,
        cursor_value: str,
        occurred_at: datetime,
    ) -> IngestionCursor:
        cursor.cursor_value = cursor_value
        cursor.status = IngestionCursorStatus.ACTIVE
        cursor.last_attempted_at = occurred_at
        cursor.last_succeeded_at = occurred_at
        cursor.failure_metadata = None
        self.session.flush()
        return cursor

    def record_failure(
        self,
        cursor: IngestionCursor,
        *,
        failure_metadata: dict[str, object],
        occurred_at: datetime,
    ) -> IngestionCursor:
        cursor.last_attempted_at = occurred_at
        cursor.failure_metadata = failure_metadata
        self.session.flush()
        return cursor

    def mark_resync_required(
        self,
        cursor: IngestionCursor,
        *,
        failure_metadata: dict[str, object],
        occurred_at: datetime,
    ) -> IngestionCursor:
        cursor.status = IngestionCursorStatus.RESYNC_REQUIRED
        cursor.last_attempted_at = occurred_at
        cursor.failure_metadata = failure_metadata
        self.session.flush()
        return cursor
