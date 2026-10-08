from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4, uuid5

import pytest

from app.contracts.evidence_lineage import LineageAttribution
from app.contracts.project_activity import ProjectActivityType
from app.models.enums import RequirementState
from app.services.policy.project_identity_authorization import AUTO_LINKED_AUDIT_EVENT
from app.services.policy.requirement_authorization import REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT
from app.services.project_activity import ProjectActivityError, ProjectActivityService
from app.services.project_resolution_review_decision import REVIEW_RESOLVED_AUDIT_EVENT
from app.services.document_filing import DOCUMENT_FILED_AUDIT_EVENT
from app.services.document_revision import DOCUMENT_REVISION_REVIEW_CREATED
from app.services.follow_up_due import FOLLOW_UP_BECAME_DUE_AUDIT_EVENT
from app.services.reply_draft_review import REPLY_DRAFT_APPROVED_AUDIT_EVENT
from app.services.reply_draft_send import (
    FOLLOW_UP_COMPLETED_AUDIT_EVENT,
    REPLY_SENT_AUDIT_EVENT,
)


def _audit(
    event_type: str,
    occurred_at: datetime,
    *,
    project_id=None,
    details=None,
    actor_type="system",
    actor_identifier=None,
    transition_id=None,
):
    return SimpleNamespace(
        id=uuid4(),
        event_type=event_type,
        occurred_at=occurred_at,
        project_id=project_id,
        correspondence_event_id=uuid4(),
        requirement_id=None,
        ai_proposal_id=uuid4(),
        policy_evaluation_id=uuid4(),
        state_transition_id=transition_id,
        review_item_id=None,
        actor_type=actor_type,
        actor_identifier=actor_identifier,
        details=details or {},
    )


def _service(project_id, audits):
    projects = MagicMock()
    projects.get.return_value = SimpleNamespace(id=project_id)
    lineage = MagicMock()
    lineage.list_project_activity_audit_events.return_value = audits
    return ProjectActivityService(
        project_repository=projects,
        lineage_repository=lineage,
    ), lineage


def test_project_activity_is_chronological_and_excludes_technical_audits() -> None:
    project_id = uuid4()
    now = datetime.now(UTC)
    linked = _audit(
        AUTO_LINKED_AUDIT_EVENT,
        now + timedelta(seconds=2),
        project_id=project_id,
    )
    proposed = _audit(
        "requirement_reconciliation_proposed",
        now + timedelta(seconds=1),
        project_id=project_id,
    )
    technical = _audit(
        "requirement_policy_evaluated",
        now,
        project_id=project_id,
    )
    service, _ = _service(project_id, [technical, linked, proposed])

    result = service.load(project_id)

    assert [item.event_type for item in result.events] == [
        ProjectActivityType.REQUIREMENT_CHANGE_PROPOSED,
        ProjectActivityType.CORRESPONDENCE_LINKED,
    ]


def test_follow_up_due_audit_maps_to_one_business_activity_event():
    project_id = uuid4()
    requirement_id = uuid4()
    occurred_at = datetime.now(UTC)
    audit = _audit(
        FOLLOW_UP_BECAME_DUE_AUDIT_EVENT,
        occurred_at,
        project_id=project_id,
    )
    audit.requirement_id = requirement_id
    service, _ = _service(project_id, [audit])

    activity = service.load(project_id)

    assert len(activity.events) == 1
    assert activity.events[0].event_type is ProjectActivityType.FOLLOW_UP_BECAME_DUE
    assert activity.events[0].summary == "Follow-up became due."
    assert activity.events[0].requirement_id == requirement_id


def test_reply_draft_approval_is_derived_as_human_project_activity():
    project_id = uuid4()
    requirement_id = uuid4()
    audit = _audit(
        REPLY_DRAFT_APPROVED_AUDIT_EVENT,
        datetime.now(UTC),
        project_id=project_id,
        actor_type="authenticated_operator",
        actor_identifier="operator-subject",
    )
    audit.requirement_id = requirement_id
    service, _ = _service(project_id, [audit])

    event = service.load(project_id).events[0]

    assert event.event_type is ProjectActivityType.REPLY_DRAFT_APPROVED
    assert event.summary == "Reply draft approved."
    assert event.authenticated_operator_subject == "operator-subject"


def test_reply_delivery_and_follow_up_completion_are_distinct_activity_events():
    project_id = uuid4()
    now = datetime.now(UTC)
    sent = _audit(REPLY_SENT_AUDIT_EVENT, now, project_id=project_id)
    completed = _audit(
        FOLLOW_UP_COMPLETED_AUDIT_EVENT,
        now + timedelta(seconds=1),
        project_id=project_id,
    )
    service, _ = _service(project_id, [completed, sent])

    events = service.load(project_id).events

    assert [event.event_type for event in events] == [
        ProjectActivityType.REPLY_SENT,
        ProjectActivityType.FOLLOW_UP_COMPLETED,
    ]


def test_document_filing_is_business_activity_without_unsupported_lineage_link() -> None:
    project_id = uuid4()
    audit = _audit(
        DOCUMENT_FILED_AUDIT_EVENT,
        datetime.now(UTC),
        project_id=project_id,
        transition_id=uuid4(),
        details={"filename": "report.pdf"},
    )
    service, _ = _service(project_id, [audit])

    result = service.load(project_id)

    assert result.events[0].event_type is ProjectActivityType.DOCUMENT_FILED
    assert result.events[0].summary == 'Document "report.pdf" filed to Google Drive.'
    assert result.events[0].state_transition_id is None


def test_document_revision_decision_is_business_activity() -> None:
    project_id = uuid4()
    audit = _audit(
        DOCUMENT_REVISION_REVIEW_CREATED,
        datetime.now(UTC),
        project_id=project_id,
        transition_id=uuid4(),
    )
    service, _ = _service(project_id, [audit])

    result = service.load(project_id)

    assert result.events[0].event_type is (
        ProjectActivityType.DOCUMENT_REVISION_REVIEW_CREATED
    )
    assert result.events[0].summary == "Document revision sent for inspection."
    assert result.events[0].state_transition_id is None


def test_requirement_application_expands_to_readable_per_requirement_events() -> None:
    project_id = uuid4()
    requirement_id = uuid4()
    evidence_id = uuid4()
    transition_id = uuid4()
    audit = _audit(
        REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT,
        datetime.now(UTC),
        project_id=project_id,
        transition_id=transition_id,
    )
    service, lineage = _service(project_id, [audit])
    lineage.get_proposal.return_value = SimpleNamespace(
        input_metadata={
            "requirement_context_snapshot_schema_version": 1,
            "requirement_reconciliation_context": {
                "project_id": str(project_id),
                "authoritative_project_link_id": str(uuid4()),
                "correspondence_event_id": str(uuid4()),
                "subject_sha256": None,
                "body_sha256": "a" * 64,
                "requirements": [
                    {
                        "requirement_id": str(requirement_id),
                        "name": "Security review",
                        "description": None,
                        "current_state": RequirementState.OPEN.value,
                        "expected_date": None,
                    }
                ],
                "attachments": [],
                "existing_evidence": [],
            },
        }
    )
    lineage.get_state_transition_by_id.return_value = SimpleNamespace(
        requirement_effects=[
            {
                "requirement_id": str(requirement_id),
                "observed_state": "OPEN",
                "observed_expected_date": None,
                "current_state": "OPEN",
                "current_expected_date": None,
                "proposed_state": "PARTIAL",
                "proposed_expected_date": None,
                "decision": "ALLOW_AUTO_ACTION",
                "triggered_rule_ids": ["RID-300-OPEN-TO-PARTIAL"],
                "reasons": ["The transition is eligible."],
                "evidence_ids": [str(evidence_id)],
            }
        ]
    )

    result = service.load(project_id)

    event = result.events[0]
    assert event.event_id == uuid5(audit.id, str(requirement_id))
    assert event.requirement_id == requirement_id
    assert event.summary == 'Requirement "Security review" moved OPEN → PARTIAL.'
    assert event.state_transition_id == transition_id


def test_human_resolution_uses_operator_label_without_authentication_claim() -> None:
    project_id = uuid4()
    audit = _audit(
        REVIEW_RESOLVED_AUDIT_EVENT,
        datetime.now(UTC),
        details={"selected_project_ids": [str(project_id)]},
        actor_type="operator_supplied",
        actor_identifier="reviewer-label",
    )
    service, _ = _service(project_id, [audit])

    event = service.load(project_id).events[0]

    assert event.attribution is LineageAttribution.HUMAN
    assert event.operator_supplied_actor_label == "reviewer-label"
    assert event.authenticated_operator_subject is None
    assert "linked" in event.summary


def test_authenticated_activity_subject_is_not_labeled_operator_supplied() -> None:
    project_id = uuid4()
    audit = _audit(
        REVIEW_RESOLVED_AUDIT_EVENT,
        datetime.now(UTC),
        details={"selected_project_ids": [str(project_id)]},
        actor_type="authenticated_operator",
        actor_identifier="supabase-user-id",
    )
    service, _ = _service(project_id, [audit])

    event = service.load(project_id).events[0]

    assert event.authenticated_operator_subject == "supabase-user-id"
    assert event.operator_supplied_actor_label is None


def test_resolution_away_from_candidate_project_is_not_shown_as_a_link() -> None:
    project_id = uuid4()
    audit = _audit(
        REVIEW_RESOLVED_AUDIT_EVENT,
        datetime.now(UTC),
        details={"selected_project_ids": [str(uuid4())]},
        actor_type="operator_supplied",
    )
    service, _ = _service(project_id, [audit])

    event = service.load(project_id).events[0]

    assert event.event_type is ProjectActivityType.PROJECT_RESOLUTION_REVIEW_RESOLVED
    assert event.summary == "Project-resolution review resolved without linking this project."


def test_missing_project_or_broken_business_history_fails_safely() -> None:
    project_id = uuid4()
    service, _ = _service(project_id, [])
    service.project_repository.get.return_value = None
    with pytest.raises(ProjectActivityError, match="project was not found"):
        service.load(project_id)

    broken = _audit(
        REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT,
        datetime.now(UTC),
        project_id=project_id,
    )
    service, _ = _service(project_id, [broken])
    with pytest.raises(ProjectActivityError, match="missing its transition"):
        service.load(project_id)
