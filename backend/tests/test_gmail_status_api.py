import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from app.api.integrations import get_gmail_status_service
from app.contracts.gmail_status import GmailIntegrationStatus, GmailStatus
from app.core.auth import AuthenticatedOperator, get_supabase_jwt_verifier
from app.main import app


class TestTokenVerifier:
    def verify(self, token: str) -> AuthenticatedOperator:
        assert token == "valid-test-token"
        return AuthenticatedOperator(subject="verified-operator")


class FakeGmailStatusService:
    def load(self) -> GmailStatus:
        return GmailStatus(
            status=GmailIntegrationStatus.CONFIGURED,
            configured_account_email="configured@example.com",
            stored_authorization_present=True,
        )


@pytest.fixture
def gmail_status_api():
    app.dependency_overrides[get_supabase_jwt_verifier] = TestTokenVerifier
    app.dependency_overrides[get_gmail_status_service] = FakeGmailStatusService
    yield
    app.dependency_overrides.clear()


def _get(*, authenticated: bool):
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
            return await client.get("/integrations/gmail/status", headers=headers)

    return asyncio.run(send())


def test_gmail_status_requires_authentication(gmail_status_api) -> None:
    assert _get(authenticated=False).status_code == 401


def test_gmail_status_exposes_only_safe_operational_fields(gmail_status_api) -> None:
    response = _get(authenticated=True)

    assert response.status_code == 200
    assert response.json() == {
        "status": "CONFIGURED",
        "configured_account_email": "configured@example.com",
        "stored_authorization_present": True,
        "cursor_status": None,
        "last_attempted_at": None,
        "last_succeeded_at": None,
    }
    assert "token" not in response.text.casefold()
    assert "secret" not in response.text.casefold()
    assert "path" not in response.text.casefold()
