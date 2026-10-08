import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.reply_drafts import (
    get_reply_draft_review_service,
    get_reply_draft_send_service,
)
from app.contracts.reply_draft import ReplyDraftContent, ReplyDraftSnapshot
from app.contracts.reply_draft_send import ReplyDraftSendResult, ReplyDraftSendStatus
from app.core.auth import AuthenticatedOperator, get_supabase_jwt_verifier
from app.main import app
from app.models.enums import ReplyDraftStatus, ReplyType


class _Verifier:
    def verify(self, token: str) -> AuthenticatedOperator:
        assert token == "token"
        return AuthenticatedOperator(subject="operator")


def _snapshot() -> ReplyDraftSnapshot:
    now = datetime.now(UTC)
    return ReplyDraftSnapshot(
        id=uuid4(), follow_up_id=uuid4(), project_id=uuid4(), requirement_id=uuid4(),
        ai_proposal_id=uuid4(), source_correspondence_event_id=uuid4(),
        target_correspondence_event_id=uuid4(), project_contact_id=uuid4(),
        reply_type=ReplyType.OVERDUE_FOLLOW_UP,
        generated=ReplyDraftContent(subject="Generated", body="Generated body"),
        edited=None, effective=ReplyDraftContent(subject="Generated", body="Generated body"),
        status=ReplyDraftStatus.APPROVED, recipient_email="client@example.test",
        gmail_thread_id="thread", source_gmail_message_id="source", approved_at=now,
        approved_by_subject="operator", rejected_at=None, send_attempt_id=None,
        send_attempted_at=None, send_failure_code=None, sent_at=None,
        gmail_message_id=None, gmail_sent_thread_id=None, can_edit=True,
        can_approve=False, can_reject=True, can_send=True, can_retry_send=False,
        send_attention_required=False, generated_at=now, created_at=now, updated_at=now,
    )


class _ReviewService:
    def __init__(self, snapshot: ReplyDraftSnapshot) -> None:
        self.snapshot = snapshot
        self.session = MagicMock()
        self.edits = []

    def get(self, draft_id):
        return self.snapshot

    def list_for_project(self, project_id):
        return (self.snapshot,)

    def edit(self, draft_id, *, content, operator_subject):
        self.edits.append((content, operator_subject))
        return self.snapshot.model_copy(update={"effective": content, "edited": content})

    def approve(self, draft_id, *, operator_subject):
        return self.snapshot

    def reject(self, draft_id, *, operator_subject):
        return self.snapshot


class _SendService:
    def __init__(self, snapshot: ReplyDraftSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = []

    def send(self, draft_id, *, operator_subject):
        self.calls.append((draft_id, operator_subject))
        return ReplyDraftSendResult(
            status=ReplyDraftSendStatus.SEND_STILL_PENDING,
            reply_draft_id=draft_id,
        )


@pytest.fixture
def reply_draft_api():
    snapshot = _snapshot()
    review = _ReviewService(snapshot)
    send = _SendService(snapshot)
    app.dependency_overrides[get_supabase_jwt_verifier] = _Verifier
    app.dependency_overrides[get_reply_draft_review_service] = lambda: review
    app.dependency_overrides[get_reply_draft_send_service] = lambda: send
    yield snapshot, review, send
    app.dependency_overrides.clear()


def _request(method: str, path: str, payload=None, authenticated=True, headers=None):
    async def run():
        request_headers = dict(headers or {})
        if authenticated:
            request_headers["Authorization"] = "Bearer token"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(
                method, path, json=payload,
                headers=request_headers or None,
            )
    return asyncio.run(run())


@pytest.mark.parametrize(
    ("method", "path_suffix", "payload"),
    (
        ("GET", "", None),
        ("GET", "/project-list", None),
        ("PATCH", "", {"subject": "Edited", "body": "Edited body"}),
        ("POST", "/approve", None),
        ("POST", "/reject", None),
        ("POST", "/send", None),
    ),
)
def test_reply_draft_routes_require_authentication(reply_draft_api, method, path_suffix, payload):
    snapshot, _, _ = reply_draft_api
    path = (
        f"/projects/{snapshot.project_id}/reply-drafts"
        if path_suffix == "/project-list"
        else f"/reply-drafts/{snapshot.id}{path_suffix}"
    )
    assert _request(method, path, payload, authenticated=False).status_code == 401


def test_reply_draft_edit_cors_preflight_allows_patch(reply_draft_api):
    snapshot, _, _ = reply_draft_api

    response = _request(
        "OPTIONS",
        f"/reply-drafts/{snapshot.id}",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
        },
    )

    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_reply_draft_detail_list_edit_and_send_are_typed_and_operator_attributed(reply_draft_api):
    snapshot, review, send = reply_draft_api
    detail = _request("GET", f"/reply-drafts/{snapshot.id}")
    listing = _request("GET", f"/projects/{snapshot.project_id}/reply-drafts")
    edited = _request("PATCH", f"/reply-drafts/{snapshot.id}", {"subject": "Edited", "body": "Edited body"})
    sent = _request("POST", f"/reply-drafts/{snapshot.id}/send")

    assert detail.status_code == 200 and detail.json()["can_send"] is True
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert edited.status_code == 200 and edited.json()["effective"]["subject"] == "Edited"
    assert review.edits[0][1] == "operator"
    assert sent.status_code == 200 and sent.json()["status"] == "SEND_STILL_PENDING"
    assert send.calls == [(snapshot.id, "operator")]
