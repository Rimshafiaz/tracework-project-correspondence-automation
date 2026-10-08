import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "0006_add_document_revision_persistence.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "tracework_document_revision_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load document revision migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_migration_chains_from_0005_and_leaves_one_head() -> None:
    migration = _load_migration()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()

    assert migration.revision == "0006"
    assert migration.down_revision == "0005"
    assert heads == ["0010"]


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured",
)
def test_revision_migration_constraints_and_current_family_uniqueness() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    schema_name = "test_document_revision_migration"
    migration = _load_migration()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema_name}"'))
            connection.execute(
                text(
                    "CREATE TABLE documents ("
                    "id UUID PRIMARY KEY, project_id UUID NOT NULL, "
                    "source_attachment_id UUID NOT NULL, filename TEXT NOT NULL, "
                    "category TEXT NOT NULL, content_hash TEXT NOT NULL, "
                    "filing_status TEXT NOT NULL, drive_file_id TEXT, "
                    "drive_parent_folder_id TEXT, failure_code TEXT, filed_at TIMESTAMPTZ, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            )
            legacy_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO documents "
                    "(id, project_id, source_attachment_id, filename, category, "
                    "content_hash, filing_status) VALUES "
                    "(:id, :project, :attachment, 'legacy.pdf', 'Documents', :hash, 'PENDING')"
                ),
                {
                    "id": legacy_id,
                    "project": uuid4(),
                    "attachment": uuid4(),
                    "hash": "a" * 64,
                },
            )
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

            legacy = connection.execute(
                text(
                    "SELECT revision_status, document_family_key, revision_normalized "
                    "FROM documents WHERE id = :id"
                ),
                {"id": legacy_id},
            ).one()
            assert legacy == ("UNASSESSED", None, None)

            project_id = uuid4()
            base = {
                "project": project_id,
                "category": "Documents",
                "family": "structural plan",
                "decided": "2026-10-07T00:00:00+00:00",
                "hash": "b" * 64,
            }

            def insert_revision(
                *,
                project_id=project_id,
                family="structural plan",
                category="Documents",
                normalized="REV-1",
                order=1,
                status="CURRENT",
                decided_at="2026-10-07T00:00:00+00:00",
            ) -> None:
                connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, project_id, source_attachment_id, filename, category, "
                        "content_hash, filing_status, document_family_key, revision_label, "
                        "revision_normalized, revision_order, revision_status, revision_decided_at) "
                        "VALUES (:id, :project, :attachment, 'plan.pdf', :category, "
                        ":hash, 'PENDING', :family, 'revision label', :normalized, "
                        ":revision_order, :status, :decided)"
                    ),
                    {
                        **base,
                        "id": uuid4(),
                        "project": project_id,
                        "attachment": uuid4(),
                        "family": family,
                        "category": category,
                        "normalized": normalized,
                        "revision_order": order,
                        "status": status,
                        "decided": decided_at,
                    },
                )

            insert_revision()
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_revision(normalized="REV-2", order=2)

            # The partial uniqueness boundary is exactly project/category/family.
            insert_revision(family="fire plan")
            insert_revision(project_id=uuid4())

            # REVIEW_REQUIRED is a decided outcome but does not require parsing.
            insert_revision(
                family=None,
                normalized=None,
                order=None,
                status="REVIEW_REQUIRED",
            )

            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_revision(
                    family=None,
                    normalized="REV-2",
                    order=None,
                    status="REVIEW_REQUIRED",
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_revision(family=None, status="CURRENT")
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_revision(family=None, status="HISTORICAL")
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_revision(family=None, status="DUPLICATE")

            columns = {column["name"] for column in inspect(connection).get_columns("documents")}
            assert {
                "document_family_key",
                "revision_label",
                "revision_normalized",
                "revision_order",
                "revision_status",
                "revision_decided_at",
            } <= columns
        finally:
            transaction.rollback()
            engine.dispose()
