import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
def test_core_schema_constraints() -> None:
    engine = create_engine(DATABASE_URL)
    project_id = uuid4()
    event_id = uuid4()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert {
                "projects",
                "project_identifiers",
                "project_contacts",
                "requirements",
                "correspondence_events",
                "correspondence_project_links",
                "attachments",
                "evidence_items",
                "ai_proposals",
                "ai_proposal_evidence",
                "policy_evaluations",
                "policy_evaluation_evidence",
                "state_transitions",
                "state_transition_evidence",
                "review_items",
                "review_item_candidate_projects",
                "audit_events",
                "ingestion_cursors",
                "documents",
            } <= set(inspect(connection).get_table_names())

            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, project_code, name, normalized_name, status) "
                    "VALUES (:id, 'TEST-1', 'Test Project', 'test project', 'ACTIVE')"
                ),
                {"id": project_id},
            )
            connection.execute(
                text(
                    "INSERT INTO correspondence_events "
                    "(id, source, external_event_id, sender_identifier, body, "
                    "received_at, processing_state) VALUES "
                    "(:id, 'test', 'event-1', 'sender', '', now(), 'PENDING')"
                ),
                {"id": event_id},
            )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO correspondence_events "
                        "(id, source, external_event_id, sender_identifier, body, "
                        "received_at, processing_state) VALUES "
                        "(:id, 'test', 'event-1', 'sender', '', now(), 'PENDING')"
                    ),
                    {"id": uuid4()},
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO projects "
                        "(id, project_code, name, normalized_name, status) VALUES "
                        "(:id, 'TEST-2', 'Invalid', 'invalid', 'BAD')"
                    ),
                    {"id": uuid4()},
                )

            connection.execute(
                text(
                    "INSERT INTO requirements "
                    "(id, project_id, name, state) "
                    "VALUES (:id, :project_id, 'Approval', 'OPEN')"
                ),
                {"id": uuid4(), "project_id": project_id},
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("DELETE FROM projects WHERE id = :id"),
                    {"id": project_id},
                )

            connection.execute(
                text(
                    "INSERT INTO ingestion_cursors "
                    "(id, source, account_identifier, status, sync_scope) VALUES "
                    "(:id, 'gmail', 'test@example.com', 'UNINITIALIZED', '{}')"
                ),
                {"id": uuid4()},
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO ingestion_cursors "
                        "(id, source, account_identifier, status, sync_scope) VALUES "
                        "(:id, 'gmail', 'test@example.com', 'UNINITIALIZED', '{}')"
                    ),
                    {"id": uuid4()},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO ingestion_cursors "
                        "(id, source, account_identifier, status, sync_scope) VALUES "
                        "(:id, 'gmail', 'invalid@example.com', 'ACTIVE', '{}')"
                    ),
                    {"id": uuid4()},
                )
        finally:
            transaction.rollback()
            engine.dispose()
