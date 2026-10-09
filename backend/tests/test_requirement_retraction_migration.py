import importlib.util
from pathlib import Path
from unittest.mock import Mock
import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_ROOT = Path(__file__).parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0011_add_requirement_retraction_state.py"


def test_retraction_migration_extends_only_required_constraints(monkeypatch):
    spec = importlib.util.spec_from_file_location("requirement_retraction_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert migration.down_revision == "0010"
    assert ScriptDirectory.from_config(config).get_heads() == ["0011"]

    operations = Mock()
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    assert operations.create_check_constraint.call_count == 2
    constraints = {call.args[0]: call.args[2] for call in operations.create_check_constraint.call_args_list}
    assert "RETRACTED" in constraints["requirement_state"]
    assert "REQUIREMENT_RETRACTED" in constraints["follow_up_cancel_reason"]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured")
def test_postgres_retracted_requirement_cancels_active_follow_up_without_deleting_history():
    from app.models.project import Project
    from app.models.requirement import Requirement
    from app.models.audit_event import AuditEvent
    from app.models.follow_up import FollowUp
    from app.models.enums import RequirementState, FollowUpStatus, FollowUpCancelReason, FollowUpPurpose
    from app.repositories.requirement import RequirementRepository
    from app.repositories.follow_up import FollowUpRepository
    from app.repositories.lineage import LineageRepository
    from app.services.follow_up_lifecycle import FollowUpLifecycleService

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
            for table, value in (("requirements", "RETRACTED"), ("follow_ups", "REQUIREMENT_RETRACTED")):
                assert any(value in item["sqltext"] for item in inspect(connection).get_check_constraints(table))
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                project = Project(project_code=f"M21-CHECK-{uuid4()}", name="Rollback-only check", normalized_name="rollback-only check")
                session.add(project)
                session.flush()
                requirement = Requirement(project_id=project.id, name="Runtime requirement", state=RequirementState.OPEN, expected_date=date(2026, 10, 10))
                session.add(requirement)
                session.flush()
                origin = AuditEvent(event_type="runtime_check", actor_type="system", project_id=project.id, details={})
                correction = AuditEvent(event_type="runtime_check", actor_type="system", project_id=project.id, details={})
                historical_origin = AuditEvent(event_type="runtime_check", actor_type="system", project_id=project.id, details={})
                session.add_all([origin, correction, historical_origin])
                session.flush()
                completed = FollowUp(project_id=project.id, requirement_id=requirement.id,
                    originating_audit_event_id=historical_origin.id, purpose=FollowUpPurpose.OVERDUE_REQUIREMENT,
                    reason="Completed historical obligation", expected_date=date(2026, 10, 10), due_on=date(2026, 10, 11),
                    status=FollowUpStatus.COMPLETED, became_due_at=datetime.now(UTC), completed_at=datetime.now(UTC))
                session.add(completed)
                session.flush()
                lifecycle = FollowUpLifecycleService(session=session, requirement_repository=RequirementRepository(session),
                    follow_up_repository=FollowUpRepository(session), audit_repository=LineageRepository(session))
                follow_up = lifecycle.reconcile(requirement.id, originating_audit_event_id=origin.id).follow_up
                requirement.state = RequirementState.RETRACTED
                session.flush()
                lifecycle.reconcile(requirement.id, originating_audit_event_id=correction.id)
                session.commit()
                assert follow_up.status is FollowUpStatus.CANCELLED
                assert follow_up.cancel_reason is FollowUpCancelReason.REQUIREMENT_RETRACTED
                assert completed.status is FollowUpStatus.COMPLETED
                assert completed.cancel_reason is None
                assert session.get(Requirement, requirement.id) is requirement
                assert session.get(AuditEvent, origin.id) is origin
        finally:
            transaction.rollback()
    engine.dispose()
