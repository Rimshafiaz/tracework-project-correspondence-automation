from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.groq import GroqModel, GroqModelSettings
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from groq import AsyncGroq

from app.core.config import Settings


def build_agent_model(*, provider: str, model_name: str, settings: Settings, agent_name: str):
    if provider == "gemini":
        if settings.google_api_key is None:
            raise ValueError(f"GOOGLE_API_KEY is required to build the {agent_name} Agent")
        return (
            GoogleModel(
                model_name,
                provider=GoogleProvider(api_key=settings.google_api_key.get_secret_value()),
            ),
            GoogleModelSettings(temperature=0),
        )
    if provider == "groq":
        if settings.groq_api_key is None:
            raise ValueError(f"GROQ_API_KEY is required to build the {agent_name} Agent")
        return (
            GroqModel(
                model_name,
                provider=GroqProvider(
                    groq_client=AsyncGroq(
                        api_key=settings.groq_api_key.get_secret_value(),
                        max_retries=0,
                    )
                ),
            ),
            GroqModelSettings(temperature=0),
        )
    raise ValueError(f"unsupported AI provider: {provider}")
