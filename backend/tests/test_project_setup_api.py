import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from app.api.projects import get_project_setup_service, get_project_workspace_service
from app.contracts.project_workspace import (
    ProjectSummary,
    ProjectWorkspace,
    ProjectWorkspaceContact,
    ProjectWorkspaceIdentifier,
    ProjectWorkspaceRequirement,
)
from app.core.auth import AuthenticatedOperator, get_supabase_jwt_verifier
from app.main import app
from app.models.enums import ProjectStatus, RequirementState
from app.services.project_setup import ProjectSetupConflictError


class TestTokenVerifier:
    def verify(self, token: str) -> AuthenticatedOperator:
        assert token == "valid-test-token"
        return AuthenticatedOperator(subject="verified-operator")


class FakeSetupService:
    def __init__(self, project_id):
        self.project_id = project_id
        self.request = None
        self.operator = None
        self.error = None

    def create(self, request, *, operator):
        if self.error:
            raise self.error
        self.request = request
        self.operator = operator
        return SimpleNamespace(project_id=self.project_id)


class FakeWorkspaceService:
    def __init__(self, workspace):
        self.workspace = workspace

    def get_workspace(self, project_id):
        assert project_id == self.workspace.project.id
        return self.workspace


@pytest.fixture
def setup_api():
    now = datetime.now(UTC)
    project_id = uuid4()
    workspace = ProjectWorkspace(
        project=ProjectSummary(
            id=project_id,
            project_code="TW-001",
            name="Neutral Project",
            status=ProjectStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        ),
        identifiers=(
            ProjectWorkspaceIdentifier(
                id=uuid4(),
                identifier_type="external reference",
                display_value="REF-1",
                verified=True,
            ),
        ),
        contacts=(
            ProjectWorkspaceContact(
                id=uuid4(),
                email="trusted@example.com",
                display_name="Trusted Contact",
                role=None,
                is_active=True,
            ),
        ),
        requirements=(
            ProjectWorkspaceRequirement(
                id=uuid4(),
                name="Initial approval",
                description=None,
                state=RequirementState.OPEN,
                expected_date=None,
                created_at=now,
                updated_at=now,
            ),
        ),
    )
    setup = FakeSetupService(project_id)
    app.dependency_overrides[get_supabase_jwt_verifier] = TestTokenVerifier
    app.dependency_overrides[get_project_setup_service] = lambda: setup
    app.dependency_overrides[get_project_workspace_service] = lambda: FakeWorkspaceService(workspace)
    yield setup, workspace
    app.dependency_overrides.clear()


def _post(payload: dict, *, authenticated: bool = True):
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
            return await client.post("/projects", json=payload, headers=headers)

    return asyncio.run(send())


def _payload() -> dict:
    return {
        "name": "Neutral Project",
        "identifiers": [
            {"identifier_type": "external reference", "display_value": "REF-1"}
        ],
        "contacts": [
            {"email": "trusted@example.com", "display_name": "Trusted Contact"}
        ],
        "requirements": [{"name": "Initial approval"}],
    }


def test_authenticated_setup_returns_authoritative_workspace(setup_api) -> None:
    setup, workspace = setup_api

    response = _post(_payload())

    assert response.status_code == 201
    assert response.json()["project"]["id"] == str(workspace.project.id)
    assert response.json()["project"]["project_code"] == "TW-001"
    assert response.json()["contacts"] == [
        {
            "id": str(workspace.contacts[0].id),
            "email": "trusted@example.com",
            "display_name": "Trusted Contact",
            "role": None,
            "is_active": True,
        }
    ]
    assert "email_normalized" not in response.text
    assert response.json()["requirements"][0]["state"] == "OPEN"
    assert setup.operator.subject == "verified-operator"


def test_anonymous_setup_is_rejected(setup_api) -> None:
    setup, _ = setup_api

    response = _post(_payload(), authenticated=False)

    assert response.status_code == 401
    assert setup.request is None


def test_client_cannot_submit_requirement_state(setup_api) -> None:
    setup, _ = setup_api
    payload = _payload()
    payload["requirements"][0]["state"] = "SATISFIED"

    response = _post(payload)

    assert response.status_code == 422
    assert setup.request is None


def test_client_cannot_submit_project_code(setup_api) -> None:
    setup, _ = setup_api
    payload = _payload()
    payload["project_code"] = "TW-999"

    response = _post(payload)

    assert response.status_code == 422
    assert setup.request is None


def test_duplicate_project_code_conflict_is_sanitized(setup_api) -> None:
    setup, _ = setup_api
    setup.error = ProjectSetupConflictError("database-specific detail")

    response = _post(_payload())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "project setup conflicts with existing configuration"
    }
    assert "database-specific" not in response.text
