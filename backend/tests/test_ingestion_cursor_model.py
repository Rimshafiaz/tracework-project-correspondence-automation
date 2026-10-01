from sqlalchemy import Enum, JSON

from app.models.enums import IngestionCursorStatus
from app.models.ingestion_cursor import IngestionCursor


def test_ingestion_cursor_table_contract() -> None:
    table = IngestionCursor.__table__

    assert table.name == "ingestion_cursors"
    assert set(table.columns) == {
        table.c.id,
        table.c.source,
        table.c.account_identifier,
        table.c.cursor_value,
        table.c.status,
        table.c.sync_scope,
        table.c.last_attempted_at,
        table.c.last_succeeded_at,
        table.c.failure_metadata,
        table.c.created_at,
        table.c.updated_at,
    }
    assert table.c.cursor_value.nullable
    assert table.c.last_attempted_at.nullable
    assert table.c.last_succeeded_at.nullable
    assert table.c.failure_metadata.nullable
    assert isinstance(table.c.status.type, Enum)
    assert table.c.status.type.enum_class is IngestionCursorStatus
    assert table.c.status.default.arg is IngestionCursorStatus.UNINITIALIZED
    assert isinstance(table.c.sync_scope.type, JSON)
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_ingestion_cursors_source_not_blank",
        "ck_ingestion_cursors_account_not_blank",
        "ck_ingestion_cursors_status_cursor",
        "uq_ingestion_cursors_source_account",
    }
    assert "ix_ingestion_cursors_status" in {
        index.name for index in table.indexes
    }
