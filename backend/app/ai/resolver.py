from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from app.ai.prompts.project_resolver import PROJECT_RESOLVER_INSTRUCTIONS
from app.ai.schemas import ProjectResolution
from app.core.config import Settings


def build_project_resolver_agent(
    settings: Settings,
) -> Agent[None, ProjectResolution]:
    if settings.google_api_key is None:
        raise ValueError("GOOGLE_API_KEY is required to build the Project Resolver Agent")

    model = GoogleModel(
        settings.project_resolver_model,
        provider=GoogleProvider(
            api_key=settings.google_api_key.get_secret_value(),
        ),
    )
    return Agent(
        model,
        output_type=ProjectResolution,
        instructions=PROJECT_RESOLVER_INSTRUCTIONS,
        model_settings=GoogleModelSettings(temperature=0),
        retries={"output": 2},
    )
