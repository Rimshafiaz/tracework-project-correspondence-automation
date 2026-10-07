from sqlalchemy import Enum

from app.models.document import Document
from app.models.enums import DocumentFilingStatus


def test_document_table_is_minimal_and_enforces_filing_identity():
    table = Document.__table__

    assert table.name == "documents"
    assert set(table.columns) == {
        table.c.id,
        table.c.project_id,
        table.c.source_attachment_id,
        table.c.filename,
        table.c.category,
        table.c.content_hash,
        table.c.filing_status,
        table.c.drive_file_id,
        table.c.drive_parent_folder_id,
        table.c.failure_code,
        table.c.filed_at,
        table.c.created_at,
        table.c.updated_at,
    }
    assert isinstance(table.c.filing_status.type, Enum)
    assert table.c.filing_status.type.enum_class is DocumentFilingStatus
    assert table.c.filing_status.default.arg is DocumentFilingStatus.PENDING
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_documents_project_source_attachment",
        "uq_documents_drive_file_id",
        "ck_documents_filing_state_complete",
        "ck_documents_hash_sha256_length",
    }
    assert {index.name for index in table.indexes} >= {
        "ix_documents_project_id",
        "ix_documents_source_attachment_id",
        "ix_documents_filing_status",
    }
