import importlib.util
import os
from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from uuid import uuid4


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0009_create_reply_drafts.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tracework_reply_draft_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load reply-draft migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reply_draft_migration_chains_from_0008_and_leaves_one_head():
    migration = _load_migration()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    assert migration.revision == "0009"
    assert migration.down_revision == "0008"
    assert ScriptDirectory.from_config(config).get_heads() == ["0010"]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
def test_reply_draft_migration_enforces_foreign_keys_and_active_uniqueness():
    engine = create_engine(TEST_DATABASE_URL)
    schema_name = "test_reply_draft_migration"
    migration = _load_migration()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema_name}"'))
                for table in (
                    "follow_ups",
                    "projects",
                    "requirements",
                    "ai_proposals",
                    "correspondence_events",
                    "project_contacts",
                ):
                    connection.execute(text(f"CREATE TABLE {table} (id UUID PRIMARY KEY)"))
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()

                ids = {name: uuid4() for name in ("follow_up", "project", "requirement")}
                connection.execute(text("INSERT INTO follow_ups VALUES (:id)"), {"id": ids["follow_up"]})
                connection.execute(text("INSERT INTO projects VALUES (:id)"), {"id": ids["project"]})
                connection.execute(text("INSERT INTO requirements VALUES (:id)"), {"id": ids["requirement"]})

                def insert_draft(*, follow_up_id=ids["follow_up"], status="GENERATED"):
                    connection.execute(
                        text(
                            "INSERT INTO reply_drafts (id, follow_up_id, project_id, requirement_id, "
                            "reply_type, generated_subject, generated_body, status) "
                            "VALUES (:id, :follow_up, :project, :requirement, "
                            "'OVERDUE_FOLLOW_UP', 'Subject', 'Body', :status)"
                        ),
                        {
                            "id": uuid4(),
                            "follow_up": follow_up_id,
                            "project": ids["project"],
                            "requirement": ids["requirement"],
                            "status": status,
                        },
                    )

                insert_draft()
                with pytest.raises(IntegrityError), connection.begin_nested():
                    insert_draft()
                with pytest.raises(IntegrityError), connection.begin_nested():
                    insert_draft(follow_up_id=uuid4())

                columns = {column["name"] for column in inspect(connection).get_columns("reply_drafts")}
                assert {"follow_up_id", "project_id", "requirement_id", "ai_proposal_id", "generated_subject", "edited_subject", "status", "send_attempt_id"} <= columns
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
