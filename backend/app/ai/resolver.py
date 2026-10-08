from pydantic_ai import Agent

from app.ai.provider_model import build_agent_model
from app.ai.prompts.project_resolver import PROJECT_RESOLVER_INSTRUCTIONS
from app.ai.schemas import ProjectResolution
from app.core.config import Settings


def build_project_resolver_agent(
    settings: Settings,
) -> Agent[None, ProjectResolution]:
    model, model_settings = build_agent_model(
        provider=settings.project_resolver_provider,
        model_name=settings.project_resolver_model,
        settings=settings,
        agent_name="Project Resolver",
    )
    return Agent(
        model,
        output_type=ProjectResolution,
        instructions=PROJECT_RESOLVER_INSTRUCTIONS,
        model_settings=model_settings,
        retries={"output": 2},
    )
