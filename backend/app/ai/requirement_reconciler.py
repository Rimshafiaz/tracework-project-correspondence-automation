from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from app.ai.prompts.requirement_reconciler import REQUIREMENT_RECONCILER_INSTRUCTIONS
from app.ai.requirement_schemas import RequirementReconciliation
from app.core.config import Settings


def build_requirement_reconciler_agent(
    settings: Settings,
) -> Agent[None, RequirementReconciliation]:
    if settings.google_api_key is None:
        raise ValueError(
            "GOOGLE_API_KEY is required to build the Requirement Reconciler Agent"
        )

    model = GoogleModel(
        settings.requirement_reconciler_model,
        provider=GoogleProvider(
            api_key=settings.google_api_key.get_secret_value(),
        ),
    )
    return Agent(
        model,
        output_type=RequirementReconciliation,
        instructions=REQUIREMENT_RECONCILER_INSTRUCTIONS,
        model_settings=GoogleModelSettings(temperature=0),
        retries={"output": 2},
    )
