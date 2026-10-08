import pytest
from pydantic import SecretStr, ValidationError
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel

from app.ai.prompts.requirement_reconciler import REQUIREMENT_RECONCILER_PROMPT_VERSION
from app.ai.requirement_reconciler import build_requirement_reconciler_agent
from app.ai.requirement_schemas import RequirementReconciliation
from app.core.config import Settings

DATABASE_URL = "postgresql+psycopg://test:test@localhost/test"


def test_requirement_reconciler_uses_configured_google_model_and_no_tools() -> None:
    agent = build_requirement_reconciler_agent(
        Settings(
            database_url=DATABASE_URL,
            google_api_key=SecretStr("test-key"),
            requirement_reconciler_model="gemini-test-model",
        )
    )

    assert isinstance(agent.model, GoogleModel)
    assert agent.model.model_name == "gemini-test-model"
    assert agent.output_type is RequirementReconciliation
    assert agent._function_toolset.tools == {}
    assert REQUIREMENT_RECONCILER_PROMPT_VERSION == "requirement-reconciler-v1"


def test_requirement_reconciler_requires_api_key_only_when_built() -> None:
    settings = Settings(database_url=DATABASE_URL, google_api_key=None)

    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        build_requirement_reconciler_agent(settings)


def test_requirement_reconciler_supports_groq_without_google_key() -> None:
    agent = build_requirement_reconciler_agent(
        Settings(
            database_url=DATABASE_URL,
            requirement_reconciler_provider="groq",
            requirement_reconciler_model="openai/gpt-oss-120b",
            groq_api_key=SecretStr("test-key"),
        )
    )

    assert isinstance(agent.model, GroqModel)
    assert agent.model.model_name == "openai/gpt-oss-120b"
    assert agent.output_type is RequirementReconciliation

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        build_requirement_reconciler_agent(
            Settings(
                database_url=DATABASE_URL,
                _env_file=None,
                requirement_reconciler_provider="groq",
                requirement_reconciler_model="openai/gpt-oss-120b",
            )
        )


def test_requirement_reconciler_model_name_cannot_be_blank() -> None:
    with pytest.raises(ValidationError, match="AI model name"):
        Settings(
            database_url=DATABASE_URL,
            requirement_reconciler_model=" ",
        )


def test_reply_drafter_model_name_uses_default_and_rejects_blank() -> None:
    assert Settings(database_url=DATABASE_URL).reply_drafter_model == "gemini-3.7-flash"
    with pytest.raises(ValidationError, match="AI model name"):
        Settings(
            database_url=DATABASE_URL,
            reply_drafter_model=" ",
        )


def test_agent_provider_values_are_limited_to_gemini_or_groq() -> None:
    with pytest.raises(ValidationError, match="project_resolver_provider"):
        Settings(database_url=DATABASE_URL, project_resolver_provider="other")
