import asyncio
import os
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedOperator, require_authenticated_operator
from app.core.config import Settings
from app.db.base import Base
from app.models import CorrespondenceEvent, EvidenceItem, FollowUp, Project, ReplyDraft, Requirement, ReviewItem, StateTransition
from app.models.enums import EvidenceValidity, FollowUpStatus, RequirementState, ReviewStatus
from app.portfolio_seed import seed_portfolio, validate_target


def settings(**kwargs):
    return Settings(_env_file=None, database_url="postgresql+psycopg://operator:secret@live-host/tracework",
                    app_env="test", gmail_enabled=False, drive_enabled=False, **kwargs)


def test_seed_refuses_live_target_and_requires_disabled_integrations():
    config = settings()
    for target in (None, config.database_url, "postgresql://different:password@live-host/tracework", "sqlite:///synthetic.db"):
        with pytest.raises(ValueError):
            validate_target(config, target)
    assert validate_target(config, "postgresql://operator:secret@test-host/tracework")
    with pytest.raises(ValueError):
        validate_target(config.model_copy(update={"gmail_enabled": True}), "postgresql://operator:secret@test-host/tracework")
    with pytest.raises(ValueError):
        validate_target(config.model_copy(update={"app_env": "production"}), "postgresql://operator:secret@test-host/tracework")


def test_shared_supabase_pooler_is_distinguished_by_tenant_not_password():
    live = "postgresql://postgres.liveproject:secret@aws-1.pooler.supabase.com/postgres"
    config = settings().model_copy(update={"database_url": live})
    with pytest.raises(ValueError):
        validate_target(config, live.replace("secret", "another-secret"))
    assert validate_target(config, live.replace("liveproject", "testproject"))


def test_offline_seed_has_coherent_api_visible_history_and_fails_cleanly_on_rerun(monkeypatch):
    target = os.environ.get("TEST_DATABASE_URL")
    if not target:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL seed validation")
    validate_target(Settings().model_copy(update={"app_env": "test", "gmail_enabled": False, "drive_enabled": False}), target)
    def forbidden(*args, **kwargs):
        raise AssertionError("Portfolio setup must not call Gmail or a model")
    monkeypatch.setattr("app.adapters.gmail.reply_client.send_gmail_reply", forbidden)
    monkeypatch.setattr("pydantic_ai.Agent.run", forbidden)
    engine = create_engine(target, connect_args={"connect_timeout": 5})
    schema = f"portfolio_check_{uuid4().hex}"
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                Base.metadata.create_all(connection)
                with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                    result = asyncio.run(seed_portfolio(session))
                    counts = {model.__name__: session.scalar(select(func.count()).select_from(model)) for model in
                              (Project, CorrespondenceEvent, Requirement, ReviewItem, FollowUp, ReplyDraft)}
                    assert counts == {"Project": 3, "CorrespondenceEvent": 6, "Requirement": 7,
                                      "ReviewItem": 2, "FollowUp": 8, "ReplyDraft": 1}
                    assert session.get(ReviewItem, UUID(result["pending_review_id"])).status is ReviewStatus.PENDING
                    assert session.get(ReviewItem, UUID(result["approved_review_id"])).status is ReviewStatus.APPROVED
                    due = session.get(FollowUp, UUID(result["follow_up_id"]))
                    assert due.status is FollowUpStatus.DUE and due.originating_state_transition_id
                    assert not due.originating_audit_event_id
                    assert session.get(Requirement, due.requirement_id).expected_date == due.expected_date
                    assert session.scalar(select(func.count()).select_from(EvidenceItem).where(EvidenceItem.validity == EvidenceValidity.INVALIDATED)) == 1
                    assert session.scalar(select(func.count()).select_from(Requirement).where(Requirement.state == RequirementState.PARTIAL)) == 1
                    assert session.scalar(select(func.count()).select_from(FollowUp).where(FollowUp.status == FollowUpStatus.DUE)) == 1
                    assert session.scalar(select(func.count()).select_from(FollowUp).where(FollowUp.status == FollowUpStatus.SCHEDULED)) == 6
                    assert session.scalar(select(func.count()).select_from(FollowUp).where(FollowUp.status == FollowUpStatus.CANCELLED)) == 1
                    for evidence in session.scalars(select(EvidenceItem)):
                        assert evidence.project_id == session.get(Requirement, evidence.requirement_id).project_id
                    pending = session.get(ReviewItem, UUID(result["pending_review_id"]))
                    preview = session.get(StateTransition, pending.state_transition_id)
                    westmere = session.scalars(select(Requirement).where(Requirement.name == "Submit ventilation balancing report")).one()
                    assert westmere.expected_date.isoformat() in str(preview.current_state)
                    invalidated = session.scalars(select(EvidenceItem).where(EvidenceItem.validity == EvidenceValidity.INVALIDATED)).one()
                    assert invalidated.correspondence_event_id != session.get(ReplyDraft, UUID(result["reply_draft_id"])).source_correspondence_event_id

                    # Use the same authenticated read routers as the product, without importing its live DB engine.
                    from app.api.dependencies import get_session
                    from app.api.projects import router as projects
                    from app.api.reviews import router as reviews
                    from app.api.reply_drafts import router as drafts
                    app = FastAPI()
                    for router in (projects, reviews, drafts):
                        app.include_router(router)
                    app.dependency_overrides[get_session] = lambda: session
                    app.dependency_overrides[require_authenticated_operator] = lambda: AuthenticatedOperator(subject="synthetic-viewer")
                    with TestClient(app) as client:
                        listed = client.get("/projects")
                        assert listed.status_code == 200 and len(listed.json()) == 3
                        for project_id in result["project_ids"]:
                            workspace = client.get(f"/projects/{project_id}")
                            assert workspace.status_code == 200, workspace.text
                            assert all(item["name"] for item in workspace.json()["requirements"])
                            activity = client.get(f"/projects/{project_id}/activity")
                            assert activity.status_code == 200, activity.text
                            assert activity.json()["events"]
                            assert all(item["project_id"] == project_id for item in activity.json()["events"])
                            draft_list = client.get(f"/projects/{project_id}/reply-drafts")
                            assert draft_list.status_code == 200
                            assert all(item["project_id"] == project_id for item in draft_list.json())
                        for key in ("pending_review_id", "approved_review_id"):
                            response = client.get(f"/reviews/{result[key]}")
                            assert response.status_code == 200, response.text
                        draft = client.get(f"/reply-drafts/{result['reply_draft_id']}")
                        assert draft.status_code == 200, draft.text
                        assert draft.json()["status"] == "GENERATED"
                        assert draft.json()["effective"]["body"].startswith("Hi Marcus,")
                        assert not draft.json()["can_send"]
                        assert draft.json()["sent_at"] is None
                    with pytest.raises(ValueError, match="empty"):
                        asyncio.run(seed_portfolio(session))
                    assert session.scalar(select(func.count()).select_from(Project)) == 3
            finally:
                outer.rollback()
        with engine.connect() as connection:
            assert not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"), {"schema": schema})
    finally:
        engine.dispose()
