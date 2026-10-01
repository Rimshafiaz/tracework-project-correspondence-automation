from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Tracework"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str
    gmail_enabled: bool = False
    gmail_account_email: str | None = None
    gmail_label_id: str | None = None
    gmail_initial_after_epoch_seconds: int | None = None
    gmail_credentials_path: Path = Path(".secrets/gmail/credentials.json")
    gmail_token_path: Path = Path(".secrets/gmail/token.json")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_gmail_configuration(self) -> "Settings":
        if not self.gmail_enabled:
            return self
        required = {
            "GMAIL_ACCOUNT_EMAIL": self.gmail_account_email,
            "GMAIL_LABEL_ID": self.gmail_label_id,
            "GMAIL_INITIAL_AFTER_EPOCH_SECONDS": (
                self.gmail_initial_after_epoch_seconds
            ),
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing:
            raise ValueError(
                f"Gmail is enabled but these settings are missing: {', '.join(missing)}"
            )
        if self.gmail_initial_after_epoch_seconds < 0:
            raise ValueError("GMAIL_INITIAL_AFTER_EPOCH_SECONDS must be nonnegative")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
