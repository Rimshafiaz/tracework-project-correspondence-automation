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
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0008_create_follow_ups.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tracework_follow_up_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load follow-up migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_follow_up_migration_chains_from_0007_and_leaves_one_head():
    migration = _load_migration()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    assert migration.revision == "0008"
    assert migration.down_revision == "0007"
    assert ScriptDirectory.from_config(config).get_heads() == ["0010"]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
def test_follow_up_database_constraints_and_partial_uniqueness():
    engine = create_engine(TEST_DATABASE_URL)
    schema_name = "test_follow_up_migration"
    migration = _load_migration()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema_name}"'))
            for table in ("projects", "requirements", "state_transitions", "audit_events"):
                connection.execute(text(f"CREATE TABLE {table} (id UUID PRIMARY KEY)"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

            project_id = uuid4()
            requirement_id = uuid4()
            transition_id = uuid4()
            audit_id = uuid4()
            replacement_audit_id = uuid4()
            connection.execute(text("INSERT INTO projects VALUES (:id)"), {"id": project_id})
            connection.execute(text("INSERT INTO requirements VALUES (:id)"), {"id": requirement_id})
            connection.execute(text("INSERT INTO state_transitions VALUES (:id)"), {"id": transition_id})
            connection.execute(text("INSERT INTO audit_events VALUES (:id)"), {"id": audit_id})
            connection.execute(
                text("INSERT INTO audit_events VALUES (:id)"),
                {"id": replacement_audit_id},
            )

            def insert_follow_up(*, status="SCHEDULED", transition=transition_id, audit=None, expected="2026-10-10", due="2026-10-11", became_due=None, cancelled=None, cancel_reason=None, completed=None, superseded=None):
                follow_up_id = uuid4()
                connection.execute(
                    text("INSERT INTO follow_ups (id, project_id, requirement_id, originating_state_transition_id, originating_audit_event_id, purpose, reason, expected_date, due_on, status, superseded_by_follow_up_id, cancelled_at, cancel_reason, became_due_at, completed_at) VALUES (:id, :project, :requirement, :transition, :audit, 'OVERDUE_REQUIREMENT', 'Outstanding requirement', :expected, :due, :status, :superseded, :cancelled, :cancel_reason, :became_due, :completed)"),
                    {"id": follow_up_id, "project": project_id, "requirement": requirement_id, "transition": transition, "audit": audit, "expected": expected, "due": due, "status": status, "superseded": superseded, "cancelled": cancelled, "cancel_reason": cancel_reason, "became_due": became_due, "completed": completed},
                )
                return follow_up_id

            first_id = insert_follow_up()
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_follow_up()
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_follow_up(transition=None, audit=None)
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_follow_up(transition=transition_id, audit=audit_id)
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_follow_up(transition=None, audit=audit_id, due="2026-10-10")

            replacement_id = uuid4()
            connection.execute(
                text(
                    "UPDATE follow_ups SET status='CANCELLED', cancelled_at=now(), "
                    "cancel_reason='EXPECTED_DATE_CHANGED', "
                    "superseded_by_follow_up_id=:replacement WHERE id=:id"
                ),
                {"replacement": replacement_id, "id": first_id},
            )
            connection.execute(
                text(
                    "INSERT INTO follow_ups (id, project_id, requirement_id, "
                    "originating_audit_event_id, purpose, reason, expected_date, "
                    "due_on, status) VALUES (:id, :project, :requirement, :audit, "
                    "'OVERDUE_REQUIREMENT', 'Rescheduled requirement', "
                    "'2026-10-12', '2026-10-13', 'SCHEDULED')"
                ),
                {
                    "id": replacement_id,
                    "project": project_id,
                    "requirement": requirement_id,
                    "audit": replacement_audit_id,
                },
            )

            columns = {column["name"] for column in inspect(connection).get_columns("follow_ups")}
            assert {"expected_date", "due_on", "status", "became_due_at", "originating_state_transition_id", "originating_audit_event_id"} <= columns
        finally:
            transaction.rollback()
            engine.dispose()
