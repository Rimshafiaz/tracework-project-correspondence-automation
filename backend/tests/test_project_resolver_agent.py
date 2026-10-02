import pytest
from pydantic import SecretStr
from pydantic_ai.models.google import GoogleModel

from app.ai.resolver import build_project_resolver_agent
from app.ai.schemas import ProjectResolution
from app.core.config import Settings

DATABASE_URL = "postgresql+psycopg://test:test@localhost/test"


def test_project_resolver_agent_uses_configured_google_model_and_no_tools() -> None:
    agent = build_project_resolver_agent(
        Settings(
            database_url=DATABASE_URL,
            google_api_key=SecretStr("test-key"),
            project_resolver_model="gemini-test-model",
        )
    )

    assert isinstance(agent.model, GoogleModel)
    assert agent.model.model_name == "gemini-test-model"
    assert agent.output_type is ProjectResolution
    assert agent._function_toolset.tools == {}


def test_project_resolver_agent_requires_api_key_only_when_built() -> None:
    settings = Settings(database_url=DATABASE_URL)

    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        build_project_resolver_agent(settings)
