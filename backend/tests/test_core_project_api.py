import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from app.api.lineage import get_evidence_lineage_service
from app.api.projects import get_project_activity_service, get_project_workspace_service
from app.contracts.evidence_lineage import (
    CurrentRequirementState,
    EvidenceLineage,
    LineageAttribution,
    LineageCompleteness,
    LineageCorrespondence,
    LineageCurrentState,
    LineageEvidence,
    LineageOutcome,
    LineagePolicy,
    LineageProposal,
    LineageTransition,
)
from app.contracts.project_activity import ProjectActivity, ProjectActivityEvent, ProjectActivityType
from app.contracts.project_workspace import ProjectSummary, ProjectWorkspace
from app.core.auth import AuthenticatedOperator, get_supabase_jwt_verifier
from app.main import app
from app.models.enums import (
    EvidenceValidity,
    PolicyDecision,
    ProjectStatus,
    ProposalType,
    RequirementState,
    TransitionDisposition,
    TransitionStatus,
)
from app.services.evidence_lineage import EvidenceLineageError
from app.services.project_activity import ProjectActivityError
from app.services.project_workspace import ProjectWorkspaceNotFoundError


class TestTokenVerifier:
    def verify(self, token: str) -> AuthenticatedOperator:
        assert token == "valid-test-token"
        return AuthenticatedOperator(subject="operator-subject")


class FakeWorkspaceService:
    def __init__(self, project: ProjectSummary) -> None:
        self.project = project

    def list_projects(self):
        return (self.project,)

    def get_workspace(self, project_id):
        if project_id != self.project.id:
            raise ProjectWorkspaceNotFoundError("project was not found")
        return ProjectWorkspace(project=self.project, identifiers=(), requirements=())


class FakeActivityService:
    def __init__(self, activity: ProjectActivity) -> None:
        self.activity = activity

    def load(self, project_id):
        if project_id != self.activity.project_id:
            raise ProjectActivityError("project was not found")
        return self.activity


class FakeLineageService:
    def __init__(self, transition_id, lineage: EvidenceLineage) -> None:
        self.transition_id = transition_id
        self.lineage = lineage
        self.error = None

    def load(self, transition_id):
        if self.error is not None:
            raise EvidenceLineageError(self.error)
        if transition_id != self.transition_id:
            raise EvidenceLineageError("state transition was not found")
        return self.lineage


@pytest.fixture
def api_fakes():
    now = datetime.now(UTC)
    project = ProjectSummary(
        id=uuid4(),
        project_code="GEN-1",
        name="General Project",
        status=ProjectStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    activity_event = ProjectActivityEvent(
        event_id=uuid4(),
        event_type=ProjectActivityType.REQUIREMENT_CHANGE_APPLIED,
        occurred_at=now,
        project_id=project.id,
        summary='Requirement "Approval" moved OPEN to PARTIAL.',
        attribution=LineageAttribution.AUTOMATIC,
    )
    activity = ProjectActivity(project_id=project.id, events=(activity_event,))
    transition_id = uuid4()
    requirement_id = uuid4()
    correspondence_id = uuid4()
    evidence_id = uuid4()
    proposal_id = uuid4()
    policy_id = uuid4()
    lineage = EvidenceLineage(
        completeness=LineageCompleteness.COMPLETE,
        completeness_notes=(),
        correspondence=LineageCorrespondence(
            id=correspondence_id,
            source="gmail",
            sender_identifier="sender@example.test",
            subject="Progress update",
            body="The first portion is complete.",
            received_at=now,
        ),
        attachments=(),
        evidence=(
            LineageEvidence(
                id=evidence_id,
                correspondence_event_id=correspondence_id,
                attachment_id=None,
                project_id=project.id,
                requirement_id=requirement_id,
                source_type="body",
                excerpt="The first portion is complete.",
                start_offset=0,
                end_offset=30,
                page_number=None,
                section=None,
                validity_at_proposal=EvidenceValidity.VALID,
                validity_at_policy=EvidenceValidity.VALID,
                validity_at_outcome=EvidenceValidity.VALID,
                current_validity=EvidenceValidity.INVALIDATED,
                invalidated_at=now,
                invalidation_reason="Later correction",
                linked_to_proposal=True,
                linked_to_policy=True,
                linked_to_transition=True,
            ),
        ),
        proposal=LineageProposal(
            id=proposal_id,
            proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
            model_identifier="test-model",
            prompt_version="requirement-reconciler/1",
            input_hash="input-hash",
            structured_output={},
            created_at=now,
        ),
        policy=LineagePolicy(
            id=policy_id,
            policy_version="requirement-policy/1",
            decision=PolicyDecision.ALLOW_AUTO_ACTION,
            triggered_rule_ids=("RID-300-OPEN-TO-PARTIAL",),
            reasons=("The proposed low-risk transition met policy conditions.",),
            evaluated_at=now,
        ),
        transition=LineageTransition(
            id=transition_id,
            affected_entity_type="requirement_reconciliation",
            affected_entity_id=proposal_id,
            historical_current_state={"state": "OPEN"},
            historical_proposed_state={"state": "PARTIAL"},
            requirement_effects=(),
            disposition=TransitionDisposition.AUTO_APPLY,
            status=TransitionStatus.APPLIED,
            created_at=now,
            applied_at=now,
        ),
        review=None,
        audit_events=(),
        historical_outcome=LineageOutcome(
            attribution=LineageAttribution.AUTOMATIC,
            occurred_at=now,
            authenticated_operator_subject=None,
            operator_supplied_actor_label=None,
        ),
        current_state=LineageCurrentState(
            linked_project_ids=(project.id,),
            requirements=(
                CurrentRequirementState(
                    requirement_id=requirement_id,
                    exists=True,
                    project_id=project.id,
                    state=RequirementState.SATISFIED,
                    expected_date=None,
                ),
            ),
        ),
    )
    workspace = FakeWorkspaceService(project)
    activity_service = FakeActivityService(activity)
    lineage_service = FakeLineageService(transition_id, lineage)
    app.dependency_overrides[get_supabase_jwt_verifier] = TestTokenVerifier
    app.dependency_overrides[get_project_workspace_service] = lambda: workspace
    app.dependency_overrides[get_project_activity_service] = lambda: activity_service
    app.dependency_overrides[get_evidence_lineage_service] = lambda: lineage_service
    yield project, transition_id, lineage_service
    app.dependency_overrides.clear()


def _request(path: str, *, authenticated: bool = True):
    async def send():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            headers = (
                {"Authorization": "Bearer valid-test-token"}
                if authenticated
                else None
            )
            return await client.get(path, headers=headers)

    return asyncio.run(send())


def test_project_routes_require_authentication(api_fakes) -> None:
    project, _, _ = api_fakes

    assert _request("/projects", authenticated=False).status_code == 401
    assert _request(f"/projects/{project.id}", authenticated=False).status_code == 401
    assert (
        _request(f"/projects/{project.id}/activity", authenticated=False).status_code
        == 401
    )


def test_authenticated_project_list_and_detail(api_fakes) -> None:
    project, _, _ = api_fakes

    listed = _request("/projects")
    detailed = _request(f"/projects/{project.id}")

    assert listed.status_code == 200
    assert listed.json()[0]["project_code"] == "GEN-1"
    assert detailed.status_code == 200
    assert detailed.json()["project"]["id"] == str(project.id)
    assert detailed.json()["requirements"] == []


def test_unknown_project_detail_is_not_found(api_fakes) -> None:
    response = _request(f"/projects/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "project was not found"}


def test_project_activity_delegates_to_existing_service(api_fakes) -> None:
    project, _, _ = api_fakes

    response = _request(f"/projects/{project.id}/activity")

    assert response.status_code == 200
    assert response.json()["events"][0]["event_type"] == "REQUIREMENT_CHANGE_APPLIED"


def test_unknown_project_activity_is_not_found(api_fakes) -> None:
    response = _request(f"/projects/{uuid4()}/activity")

    assert response.status_code == 404
    assert response.json() == {"detail": "project was not found"}


def test_lineage_requires_authentication(api_fakes) -> None:
    _, transition_id, _ = api_fakes

    assert (
        _request(f"/transitions/{transition_id}/lineage", authenticated=False).status_code
        == 401
    )


def test_lineage_preserves_historical_and_current_truth(api_fakes) -> None:
    _, transition_id, _ = api_fakes

    response = _request(f"/transitions/{transition_id}/lineage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"][0]["validity_at_outcome"] == "VALID"
    assert payload["evidence"][0]["current_validity"] == "INVALIDATED"
    assert payload["transition"]["historical_proposed_state"]["state"] == "PARTIAL"
    assert payload["current_state"]["requirements"][0]["state"] == "SATISFIED"


def test_missing_transition_is_not_found(api_fakes) -> None:
    response = _request(f"/transitions/{uuid4()}/lineage")

    assert response.status_code == 404
    assert response.json() == {"detail": "state transition was not found"}


def test_broken_lineage_returns_sanitized_conflict(api_fakes) -> None:
    _, transition_id, lineage_service = api_fakes
    lineage_service.error = "transition proposal or policy was not found"

    response = _request(f"/transitions/{transition_id}/lineage")

    assert response.status_code == 409
    assert response.json() == {"detail": "evidence lineage is inconsistent"}
    assert "proposal" not in response.text


def test_health_remains_public(api_fakes, monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.database_is_available", lambda: True)

    response = _request("/health", authenticated=False)

    assert response.status_code == 200
