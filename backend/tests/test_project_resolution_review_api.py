import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from app.ai.schemas import ProjectResolution, ResolutionConcern, ResolutionStatus
from app.api.project_resolution_reviews import (
    get_review_decision_service,
    get_review_query_service,
)
from app.contracts.project_candidate import ProjectCandidateSet
from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewAction,
    ProjectResolutionReviewApproval,
    ProjectResolutionReviewCorrespondence,
    ProjectResolutionReviewDetail,
    ProjectResolutionReviewDecisionContext,
    ProjectResolutionReviewPreview,
    ProjectResolutionReviewReplacementAssignment,
    ProjectResolutionReviewSummary,
)
from app.contracts.transition_preview import PolicyEvaluationSnapshot
from app.core.auth import AuthenticatedOperator, get_supabase_jwt_verifier
from app.main import app
from app.models.enums import (
    PolicyDecision,
    ReviewStatus,
    TransitionDisposition,
)
from app.services.project_resolution_review_decision import (
    ProjectResolutionReviewDecisionError,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryError,
)


AUTHENTICATED_SUBJECT = "supabase-user-id"


class TestTokenVerifier:
    def verify(self, token: str) -> AuthenticatedOperator:
        assert token == "valid-test-token"
        return AuthenticatedOperator(
            subject=AUTHENTICATED_SUBJECT,
            email="operator@example.test",
        )


@pytest.fixture(autouse=True)
def authenticated_operator_override():
    app.dependency_overrides[get_supabase_jwt_verifier] = TestTokenVerifier
    yield
    app.dependency_overrides.clear()


def _request(method: str, path: str, *, json=None, authenticated=True):
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
            return await client.request(method, path, json=json, headers=headers)

    return asyncio.run(send())


def _summary(review_id, event_id) -> ProjectResolutionReviewSummary:
    return ProjectResolutionReviewSummary(
        review_item_id=review_id,
        correspondence_event_id=event_id,
        status=ReviewStatus.PENDING,
        review_reason="Human review is required.",
        created_at=datetime.now(UTC),
    )


def _detail(review_id, event_id) -> ProjectResolutionReviewDetail:
    policy_id = uuid4()
    proposal_id = uuid4()
    return ProjectResolutionReviewDetail(
        review=_summary(review_id, event_id),
        state_transition_id=uuid4(),
        proposal_id=proposal_id,
        policy_evaluation_id=policy_id,
        correspondence=ProjectResolutionReviewCorrespondence(
            correspondence_event_id=event_id,
            source="gmail",
            sender_identifier="sender@example.test",
            subject="Project question",
            body="Which project is this for?",
            received_at=datetime.now(UTC),
        ),
        preview=ProjectResolutionReviewPreview(
            correspondence_event_id=event_id,
            resolver_status=ResolutionStatus.NO_MATCH,
            policy=PolicyEvaluationSnapshot(
                id=policy_id,
                policy_version="project-identity/1",
                decision=PolicyDecision.REVIEW_REQUIRED,
                triggered_rule_ids=("PID-100-NO-MATCH",),
                reasons=("Manual assignment is required.",),
            ),
            disposition=TransitionDisposition.REVIEW,
            requires_manual_project_assignment=True,
        ),
        candidate_set=ProjectCandidateSet(),
        resolution=ProjectResolution(
            status=ResolutionStatus.NO_MATCH,
            concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
        ),
    )


class FakeQueryService:
    def __init__(self, review_id, event_id) -> None:
        self.review_id = review_id
        self.summary = _summary(review_id, event_id)
        self.detail = _detail(review_id, event_id)

    def list_open(self):
        return (self.summary,)

    def get_detail(self, review_id):
        if review_id != self.review_id:
            raise ProjectResolutionReviewQueryError(
                "project-resolution review item was not found"
            )
        return self.detail


class FakeDecisionService:
    def __init__(self) -> None:
        self.calls = []

    def approve(self, review_id, decision):
        self.calls.append(("approve", review_id, decision))
        return self._result(
            review_id,
            ProjectResolutionReviewAction.APPROVE_PROPOSAL,
        )

    def assign_or_correct(self, review_id, decision):
        self.calls.append(("assign", review_id, decision))
        return self._result(
            review_id,
            ProjectResolutionReviewAction.MANUAL_ASSIGNMENT,
            decision.project_ids,
        )

    def reject(self, review_id, decision):
        self.calls.append(("reject", review_id, decision))
        return self._result(review_id, ProjectResolutionReviewAction.REJECT)

    @staticmethod
    def _result(review_id, action, project_ids=()):
        links = tuple(
            SimpleNamespace(id=uuid4(), project_id=project_id)
            for project_id in project_ids
        )
        return SimpleNamespace(
            review_item=SimpleNamespace(
                id=review_id,
                status=(
                    ReviewStatus.REJECTED
                    if action is ProjectResolutionReviewAction.REJECT
                    else ReviewStatus.CORRECTED
                    if action is ProjectResolutionReviewAction.MANUAL_ASSIGNMENT
                    else ReviewStatus.APPROVED
                ),
            ),
            action=action,
            project_links=links,
            idempotent_replay=False,
        )


def test_list_and_detail_endpoints_expose_read_only_review_context() -> None:
    review_id = uuid4()
    event_id = uuid4()
    service = FakeQueryService(review_id, event_id)
    app.dependency_overrides[get_review_query_service] = lambda: service
    try:
        listed = _request("GET", "/reviews/project-resolution")
        detail = _request("GET", f"/reviews/project-resolution/{review_id}")
    finally:
        app.dependency_overrides.clear()

    assert listed.status_code == 200
    assert listed.json()[0]["review_item_id"] == str(review_id)
    assert detail.status_code == 200
    assert detail.json()["correspondence"]["body"] == "Which project is this for?"
    assert detail.json()["preview"]["requires_manual_project_assignment"] is True


def test_decision_endpoints_keep_approval_and_assignment_distinct() -> None:
    review_id = uuid4()
    project_id = uuid4()
    service = FakeDecisionService()
    app.dependency_overrides[get_review_decision_service] = lambda: service
    try:
        approved = _request(
            "POST",
            f"/reviews/project-resolution/{review_id}/approve",
            json={"comment": "approved"},
        )
        assigned = _request(
            "POST",
            f"/reviews/project-resolution/{review_id}/assign",
            json={
                "project_ids": [str(project_id)],
            },
        )
        rejected = _request(
            "POST",
            f"/reviews/project-resolution/{review_id}/reject",
            json={},
        )
    finally:
        app.dependency_overrides.clear()

    assert approved.status_code == 200
    assert assigned.status_code == 200
    assert rejected.status_code == 200
    approval = service.calls[0][2]
    assignment = service.calls[1][2]
    rejection = service.calls[2][2]
    assert isinstance(approval, ProjectResolutionReviewApproval)
    assert not hasattr(approval, "project_ids")
    assert isinstance(assignment, ProjectResolutionReviewReplacementAssignment)
    assert assignment.project_ids == (project_id,)
    assert isinstance(rejection, ProjectResolutionReviewDecisionContext)
    assert all(
        call[2].actor.actor_type == "authenticated_operator"
        for call in service.calls
    )
    assert all(
        call[2].actor.actor_identifier == AUTHENTICATED_SUBJECT
        for call in service.calls
    )


def test_request_body_cannot_spoof_actor_identity() -> None:
    review_id = uuid4()
    service = FakeDecisionService()
    app.dependency_overrides[get_review_decision_service] = lambda: service
    try:
        response = _request(
            "POST",
            f"/reviews/project-resolution/{review_id}/approve",
            json={
                "actor_identifier": "another-user-id",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert service.calls == []


def test_service_errors_have_small_explicit_http_mappings() -> None:
    review_id = uuid4()
    query = FakeQueryService(uuid4(), uuid4())
    decision = FakeDecisionService()

    def reject_missing(review_id, request):
        raise ProjectResolutionReviewDecisionError(
            "project-resolution review item was not found"
        )

    decision.reject = reject_missing
    app.dependency_overrides[get_review_query_service] = lambda: query
    app.dependency_overrides[get_review_decision_service] = lambda: decision
    try:
        missing_detail = _request(
            "GET",
            f"/reviews/project-resolution/{review_id}",
        )
        missing_decision = _request(
            "POST",
            f"/reviews/project-resolution/{review_id}/reject",
            json={},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_detail.status_code == 404
    assert missing_decision.status_code == 404


def test_anonymous_review_reads_are_rejected() -> None:
    review_id = uuid4()
    service = FakeQueryService(review_id, uuid4())
    app.dependency_overrides[get_review_query_service] = lambda: service

    listed = _request(
        "GET",
        "/reviews/project-resolution",
        authenticated=False,
    )
    detail = _request(
        "GET",
        f"/reviews/project-resolution/{review_id}",
        authenticated=False,
    )

    assert listed.status_code == 401
    assert detail.status_code == 401


@pytest.mark.parametrize("action", ["approve", "assign", "reject"])
def test_anonymous_review_mutations_are_rejected(action) -> None:
    review_id = uuid4()
    project_id = uuid4()
    service = FakeDecisionService()
    app.dependency_overrides[get_review_decision_service] = lambda: service
    payload = {"project_ids": [str(project_id)]} if action == "assign" else {}

    response = _request(
        "POST",
        f"/reviews/project-resolution/{review_id}/{action}",
        json=payload,
        authenticated=False,
    )

    assert response.status_code == 401
    assert service.calls == []
