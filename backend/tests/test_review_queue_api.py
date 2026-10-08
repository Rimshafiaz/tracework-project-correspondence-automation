import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from app.ai.requirement_schemas import RequirementReconciliation
from app.ai.schemas import ProjectResolution, ResolutionConcern, ResolutionStatus
from app.api.reviews import (
    get_requirement_review_decision_service,
    get_review_queue_query_service,
)
from app.contracts.requirement_review_decision import RequirementReviewAction
from app.contracts.project_candidate import ProjectCandidateSet
from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewCorrespondence,
    ProjectResolutionReviewDetail,
    ProjectResolutionReviewPreview,
    ProjectResolutionReviewSummary,
)
from app.contracts.requirement_policy import RequirementPolicyTransitionPreview
from app.contracts.requirement_reconciliation import RequirementContextSnapshot
from app.contracts.requirement_review import RequirementReviewHandoff
from app.contracts.review_queue import (
    NewRequirementReviewReadDetail,
    PROJECT_RESOLUTION_ALLOWED_ACTIONS,
    REQUIREMENT_REVIEW_ALLOWED_ACTIONS,
    ProjectResolutionReviewReadDetail,
    RequirementChangeReviewReadDetail,
    ReviewQueueSummary,
    DocumentRevisionReviewAttachment,
    DocumentRevisionReviewDocument,
    DocumentRevisionReviewReadDetail,
)
from app.contracts.document_revision import DocumentRevisionRule
from app.contracts.transition_preview import PolicyEvaluationSnapshot, TransitionState
from app.core.auth import AuthenticatedOperator, get_supabase_jwt_verifier
from app.main import app
from app.models.enums import PolicyDecision, ReviewStatus, ReviewType, TransitionDisposition
from app.services.review_queue import ReviewQueueIntegrityError, ReviewQueueNotFoundError


class TestTokenVerifier:
    def verify(self, token: str) -> AuthenticatedOperator:
        assert token == "valid-test-token"
        return AuthenticatedOperator(subject="operator-subject")


class FakeReviewQueueService:
    def __init__(self, summaries) -> None:
        self.summaries = tuple(summaries)
        self.details = {}
        self.error = None

    def list_pending(self):
        return self.summaries

    def get_detail(self, review_id):
        if self.error == "integrity":
            raise ReviewQueueIntegrityError("sensitive internal detail")
        if review_id not in self.details:
            raise ReviewQueueNotFoundError("review item was not found")
        return self.details[review_id]


class FakeRequirementReviewDecisionService:
    def __init__(self, review) -> None:
        self.review = review
        self.calls = []

    def approve(self, review_id, *, operator_subject):
        self.calls.append(("approve", review_id, operator_subject))
        return type("Result", (), {
            "review_item": SimpleNamespace(
                id=self.review.review_item_id,
                status=ReviewStatus.APPROVED,
            ),
            "action": RequirementReviewAction.APPROVE,
            "applied_requirement_ids": (),
            "follow_up_ids": (),
            "idempotent_replay": False,
        })()

    def reject(self, review_id, *, operator_subject):
        self.calls.append(("reject", review_id, operator_subject))
        return type("Result", (), {
            "review_item": SimpleNamespace(
                id=self.review.review_item_id,
                status=ReviewStatus.REJECTED,
            ),
            "action": RequirementReviewAction.REJECT,
            "applied_requirement_ids": (),
            "follow_up_ids": (),
            "idempotent_replay": False,
        })()


def _summary(review_type):
    return ReviewQueueSummary(
        review_item_id=uuid4(),
        correspondence_event_id=uuid4(),
        review_type=review_type,
        status=ReviewStatus.PENDING,
        review_reason="Human review is required.",
        created_at=datetime.now(UTC),
        allowed_actions=(
            PROJECT_RESOLUTION_ALLOWED_ACTIONS
            if review_type is ReviewType.PROJECT_RESOLUTION
            else REQUIREMENT_REVIEW_ALLOWED_ACTIONS
            if review_type in {ReviewType.REQUIREMENT_CHANGE, ReviewType.NEW_REQUIREMENT}
            else ()
        ),
    )


def _project_resolution_detail(summary):
    policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="project-identity/1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=("PID-100-NO-MATCH",),
        reasons=("Manual assignment is required.",),
    )
    detail = ProjectResolutionReviewDetail(
        review=ProjectResolutionReviewSummary(
            review_item_id=summary.review_item_id,
            correspondence_event_id=summary.correspondence_event_id,
            status=summary.status,
            review_reason=summary.review_reason,
            created_at=summary.created_at,
        ),
        state_transition_id=uuid4(),
        proposal_id=uuid4(),
        policy_evaluation_id=policy.id,
        correspondence=ProjectResolutionReviewCorrespondence(
            correspondence_event_id=summary.correspondence_event_id,
            source="gmail",
            sender_identifier="sender@example.test",
            subject="Project question",
            body="Which project is this for?",
            received_at=datetime.now(UTC),
        ),
        preview=ProjectResolutionReviewPreview(
            correspondence_event_id=summary.correspondence_event_id,
            resolver_status=ResolutionStatus.NO_MATCH,
            policy=policy,
            disposition=TransitionDisposition.REVIEW,
            requires_manual_project_assignment=True,
        ),
        candidate_set=ProjectCandidateSet(),
        resolution=ProjectResolution(
            status=ResolutionStatus.NO_MATCH,
            concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
        ),
    )
    return ProjectResolutionReviewReadDetail(
        allowed_actions=PROJECT_RESOLUTION_ALLOWED_ACTIONS,
        detail=detail,
    )


def _requirement_detail(summary):
    project_id = uuid4()
    proposal_id = uuid4()
    transition_id = uuid4()
    policy = PolicyEvaluationSnapshot(
        id=uuid4(),
        policy_version="requirement-policy/1",
        decision=PolicyDecision.REVIEW_REQUIRED,
        triggered_rule_ids=("RID-406-NEW-REQUIREMENT",),
        reasons=("Human review is required.",),
    )
    handoff = RequirementReviewHandoff(
        correspondence_event_id=summary.correspondence_event_id,
        proposal_id=proposal_id,
        policy_evaluation_id=policy.id,
        state_transition_id=transition_id,
        project_id=project_id,
        reconciliation=RequirementReconciliation(),
        m11_snapshot=RequirementContextSnapshot(
            project_id=project_id,
            authoritative_project_link_id=uuid4(),
            correspondence_event_id=summary.correspondence_event_id,
            body_sha256="a" * 64,
            requirements=(),
        ),
        current_requirements=(),
        transition_preview=RequirementPolicyTransitionPreview(
            current_state=TransitionState(
                entity_type="requirement_reconciliation",
                entity_id=proposal_id,
                values={"project_id": str(project_id)},
            ),
            proposed_state=TransitionState(
                entity_type="requirement_reconciliation",
                entity_id=proposal_id,
                values={"project_id": str(project_id)},
            ),
            policy=policy,
            disposition=TransitionDisposition.REVIEW,
        ),
    )
    correspondence = ProjectResolutionReviewCorrespondence(
        correspondence_event_id=summary.correspondence_event_id,
        source="gmail",
        sender_identifier="sender@example.test",
        subject="Requirement update",
        body="Please review the requirement proposal.",
        received_at=datetime.now(UTC),
    )
    detail_type = (
        NewRequirementReviewReadDetail
        if summary.review_type is ReviewType.NEW_REQUIREMENT
        else RequirementChangeReviewReadDetail
    )
    return detail_type(
        allowed_actions=REQUIREMENT_REVIEW_ALLOWED_ACTIONS,
        review=summary,
        correspondence=correspondence,
        handoff=handoff,
    )


def _document_revision_detail(summary):
    project_id = uuid4()
    attachment_id = uuid4()
    return DocumentRevisionReviewReadDetail(
        review=summary,
        correspondence=ProjectResolutionReviewCorrespondence(
            correspondence_event_id=summary.correspondence_event_id,
            source="gmail",
            sender_identifier="sender@example.test",
            subject="Drawing revision",
            body="Please inspect the attached revision.",
            received_at=datetime.now(UTC),
        ),
        attachment=DocumentRevisionReviewAttachment(
            attachment_id=attachment_id,
            filename="Structural Plan R4.pdf",
            mime_type="application/pdf",
            content_hash="b" * 64,
        ),
        state_transition_id=uuid4(),
        transition_status="PREVIEWED",
        disposition="REVIEW",
        incoming_document=DocumentRevisionReviewDocument(
            document_id=uuid4(),
            source_attachment_id=attachment_id,
            filename="Structural Plan R4.pdf",
            project_id=project_id,
            project_code="TW-001",
            project_name="Test Project",
            category="Documents",
            document_family_key="structural plan",
            revision_label="R4",
            revision_normalized="REV-4",
            revision_order=4,
            content_hash="b" * 64,
        ),
        reasons=("The same revision label exists with different content.",),
        triggered_rule_ids=(
            DocumentRevisionRule.SAME_REVISION_DIFFERENT_CONTENT_REVIEW,
        ),
    )


@pytest.fixture
def review_api():
    summaries = [
        _summary(ReviewType.PROJECT_RESOLUTION),
        _summary(ReviewType.REQUIREMENT_CHANGE),
        _summary(ReviewType.NEW_REQUIREMENT),
        _summary(ReviewType.DOCUMENT_REVISION),
    ]
    service = FakeReviewQueueService(summaries)
    service.details = {
        summaries[0].review_item_id: _project_resolution_detail(summaries[0]),
        summaries[1].review_item_id: _requirement_detail(summaries[1]),
        summaries[2].review_item_id: _requirement_detail(summaries[2]),
        summaries[3].review_item_id: _document_revision_detail(summaries[3]),
    }
    app.dependency_overrides[get_supabase_jwt_verifier] = TestTokenVerifier
    app.dependency_overrides[get_review_queue_query_service] = lambda: service
    yield service, summaries
    app.dependency_overrides.clear()


def _request(path, *, authenticated=True):
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


def _post(path, *, authenticated=True):
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
            return await client.post(path, headers=headers)

    return asyncio.run(send())


def test_consolidated_review_list_requires_authentication(review_api) -> None:
    assert _request("/reviews", authenticated=False).status_code == 401


def test_consolidated_review_list_exposes_mixed_capabilities(review_api) -> None:
    _, summaries = review_api

    response = _request("/reviews")

    assert response.status_code == 200
    payload = response.json()
    assert [item["review_type"] for item in payload] == [
        "PROJECT_RESOLUTION",
        "REQUIREMENT_CHANGE",
        "NEW_REQUIREMENT",
        "DOCUMENT_REVISION",
    ]
    assert payload[0]["allowed_actions"] == [
        "APPROVE",
        "ASSIGN_OR_CORRECT",
        "REJECT",
    ]
    assert payload[1]["allowed_actions"] == ["APPROVE", "REJECT"]
    assert payload[2]["allowed_actions"] == ["APPROVE", "REJECT"]
    assert payload[3]["allowed_actions"] == []
    assert [item["review_item_id"] for item in payload] == [
        str(item.review_item_id) for item in summaries
    ]


@pytest.mark.parametrize(
    ("index", "review_type"),
    [
        (0, "PROJECT_RESOLUTION"),
        (1, "REQUIREMENT_CHANGE"),
        (2, "NEW_REQUIREMENT"),
        (3, "DOCUMENT_REVISION"),
    ],
)
def test_consolidated_review_detail_is_discriminated_by_type(
    review_api,
    index,
    review_type,
) -> None:
    _, summaries = review_api

    response = _request(f"/reviews/{summaries[index].review_item_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_type"] == review_type
    if index == 0:
        assert payload["detail"]["preview"]["policy"]["policy_version"] == (
            "project-identity/1"
        )
        assert payload["allowed_actions"] == [
            "APPROVE",
            "ASSIGN_OR_CORRECT",
            "REJECT",
        ]
    elif index in {1, 2}:
        assert payload["handoff"]["transition_preview"]["policy"][
            "policy_version"
        ] == "requirement-policy/1"
        assert payload["allowed_actions"] == ["APPROVE", "REJECT"]
    else:
        assert payload["policy_version"] == "document-revision/1"
        assert payload["incoming_document"]["revision_normalized"] == "REV-4"
        assert payload["allowed_actions"] == []


def test_unknown_review_is_not_found(review_api) -> None:
    response = _request(f"/reviews/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "review item was not found"}


def test_broken_review_history_is_sanitized(review_api) -> None:
    service, _ = review_api
    service.error = "integrity"

    response = _request(f"/reviews/{uuid4()}")

    assert response.status_code == 409
    assert response.json() == {"detail": "review history is inconsistent"}
    assert "sensitive" not in response.text


def test_requirement_review_decisions_require_authentication(review_api) -> None:
    _, summaries = review_api

    response = _post(f"/reviews/{summaries[1].review_item_id}/approve", authenticated=False)

    assert response.status_code == 401


def test_requirement_review_decision_routes_delegate_only_human_action(review_api) -> None:
    _, summaries = review_api
    summary = summaries[1]
    decision_service = FakeRequirementReviewDecisionService(summary)
    app.dependency_overrides[get_requirement_review_decision_service] = lambda: decision_service

    response = _post(f"/reviews/{summary.review_item_id}/approve")

    assert response.status_code == 200
    assert response.json()["action"] == "APPROVE"
    assert decision_service.calls == [
        ("approve", summary.review_item_id, "operator-subject")
    ]
