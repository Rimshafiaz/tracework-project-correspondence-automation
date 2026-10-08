from pydantic_ai import Agent

from app.ai.provider_model import build_agent_model
from app.ai.prompts.requirement_reconciler import REQUIREMENT_RECONCILER_INSTRUCTIONS
from app.ai.requirement_schemas import RequirementReconciliation
from app.core.config import Settings


def build_requirement_reconciler_agent(
    settings: Settings,
) -> Agent[None, RequirementReconciliation]:
    model, model_settings = build_agent_model(
        provider=settings.requirement_reconciler_provider,
        model_name=settings.requirement_reconciler_model,
        settings=settings,
        agent_name="Requirement Reconciler",
    )
    return Agent(
        model,
        output_type=RequirementReconciliation,
        instructions=REQUIREMENT_RECONCILER_INSTRUCTIONS,
        model_settings=model_settings,
        retries={"output": 2},
    )
