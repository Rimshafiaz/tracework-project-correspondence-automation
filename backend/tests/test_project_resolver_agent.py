import pytest
from pydantic import SecretStr
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openrouter import OpenRouterModel

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
    assert agent.model.provider.client._api_client._http_options.retry_options.attempts == 1
    assert agent.output_type is ProjectResolution
    assert agent._function_toolset.tools == {}


def test_project_resolver_agent_requires_api_key_only_when_built() -> None:
    settings = Settings(database_url=DATABASE_URL, google_api_key=None)

    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        build_project_resolver_agent(settings)


def test_project_resolver_agent_supports_groq_without_google_key() -> None:
    agent = build_project_resolver_agent(
        Settings(
            database_url=DATABASE_URL,
            project_resolver_provider="groq",
            project_resolver_model="openai/gpt-oss-120b",
            groq_api_key=SecretStr("test-key"),
        )
    )

    assert isinstance(agent.model, GroqModel)
    assert agent.model.model_name == "openai/gpt-oss-120b"
    assert agent.model.provider.client.max_retries == 0
    assert agent.output_type is ProjectResolution

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        build_project_resolver_agent(
            Settings(
                database_url=DATABASE_URL,
                _env_file=None,
                project_resolver_provider="groq",
                project_resolver_model="openai/gpt-oss-120b",
            )
        )


def test_project_resolver_agent_supports_openrouter_without_google_or_groq_key() -> None:
    agent = build_project_resolver_agent(
        Settings(
            database_url=DATABASE_URL,
            project_resolver_provider="openrouter",
            project_resolver_model="google/gemma-4-26b-a4b-it:free",
            openrouter_api_key=SecretStr("test-key"),
        )
    )

    assert isinstance(agent.model, OpenRouterModel)
    assert agent.model.model_name == "google/gemma-4-26b-a4b-it:free"
    assert agent.model.provider.client.max_retries == 0
    assert agent.output_type is ProjectResolution
    assert agent._function_toolset.tools == {}

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_project_resolver_agent(
            Settings(
                database_url=DATABASE_URL,
                _env_file=None,
                project_resolver_provider="openrouter",
                project_resolver_model="google/gemma-4-26b-a4b-it:free",
            )
        )
