from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    attachment_max_size_bytes: int = Field(default=26_214_400, gt=0)
    pdf_max_pages: int = Field(default=250, gt=0)
    extraction_max_characters: int = Field(default=1_000_000, gt=0)
    docx_max_paragraphs: int = Field(default=10_000, gt=0)
    docx_max_tables: int = Field(default=500, gt=0)
    docx_max_table_cells: int = Field(default=50_000, gt=0)
    google_api_key: SecretStr | None = None
    project_resolver_model: str = "gemini-3.7-flash"
    requirement_reconciler_model: str = "gemini-3.7-flash"
    requirement_reconciler_max_requirements: int = Field(default=100, gt=0)
    requirement_reconciler_max_attachments: int = Field(default=20, gt=0)
    requirement_reconciler_max_source_characters: int = Field(
        default=200_000,
        gt=0,
    )

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

    @field_validator("project_resolver_model", "requirement_reconciler_model")
    @classmethod
    def reject_blank_ai_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("AI model name must not be blank")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
