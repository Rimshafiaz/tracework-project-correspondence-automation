from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Tracework"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str
    supabase_auth_issuer: str | None = None
    supabase_auth_audience: str = "authenticated"
    cors_allowed_origins: str = "http://localhost:5173"
    gmail_enabled: bool = False
    gmail_account_email: str | None = None
    gmail_reply_message_id_domain: str | None = None
    gmail_label_id: str | None = None
    gmail_initial_after_epoch_seconds: int | None = None
    gmail_credentials_path: Path = Path(".secrets/gmail/credentials.json")
    gmail_token_path: Path = Path(".secrets/gmail/token.json")
    drive_enabled: bool = False
    drive_root_folder_name: str = "Tracework"
    drive_default_category_folder: str = "Documents"
    attachment_max_size_bytes: int = Field(default=26_214_400, gt=0)
    pdf_max_pages: int = Field(default=250, gt=0)
    extraction_max_characters: int = Field(default=1_000_000, gt=0)
    docx_max_paragraphs: int = Field(default=10_000, gt=0)
    docx_max_tables: int = Field(default=500, gt=0)
    docx_max_table_cells: int = Field(default=50_000, gt=0)
    google_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    project_resolver_provider: Literal["gemini", "groq"] = "gemini"
    requirement_reconciler_provider: Literal["gemini", "groq"] = "gemini"
    reply_drafter_provider: Literal["gemini", "groq"] = "gemini"
    project_resolver_model: str = "gemini-3.7-flash"
    requirement_reconciler_model: str = "gemini-3.7-flash"
    reply_drafter_model: str = "gemini-3.7-flash"
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
    def validate_runtime_configuration(self) -> "Settings":
        if self.app_env == "production" and self.supabase_auth_issuer is None:
            raise ValueError("SUPABASE_AUTH_ISSUER is required in production")
        if self.gmail_enabled:
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
                    "Gmail is enabled but these settings are missing: "
                    f"{', '.join(missing)}"
                )
            if self.gmail_initial_after_epoch_seconds < 0:
                raise ValueError(
                    "GMAIL_INITIAL_AFTER_EPOCH_SECONDS must be nonnegative"
                )
        return self

    @field_validator("supabase_auth_issuer")
    @classmethod
    def validate_supabase_auth_issuer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SUPABASE_AUTH_ISSUER must be an HTTP(S) URL")
        if not parsed.path.endswith("/auth/v1"):
            raise ValueError("SUPABASE_AUTH_ISSUER must end with /auth/v1")
        return value

    @field_validator("supabase_auth_audience")
    @classmethod
    def validate_supabase_auth_audience(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("SUPABASE_AUTH_AUDIENCE must not be blank")
        return value

    @field_validator("gmail_reply_message_id_domain")
    @classmethod
    def validate_gmail_reply_message_id_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower().rstrip(".")
        if not value:
            raise ValueError("GMAIL_REPLY_MESSAGE_ID_DOMAIN must not be blank")
        if len(value) > 253 or "." not in value:
            raise ValueError("GMAIL_REPLY_MESSAGE_ID_DOMAIN must be a domain name")
        labels = value.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
            for label in labels
        ):
            raise ValueError("GMAIL_REPLY_MESSAGE_ID_DOMAIN must be a domain name")
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_allowed_origins(cls, value: str) -> str:
        origins = tuple(
            origin.strip().rstrip("/")
            for origin in value.split(",")
            if origin.strip()
        )
        if not origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin")
        if "*" in origins or len(origins) != len(set(origins)):
            raise ValueError("CORS_ALLOWED_ORIGINS must be explicit and unique")
        for origin in origins:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS entries must be HTTP(S) origins"
                )
        return ",".join(origins)

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(self.cors_allowed_origins.split(","))

    @field_validator(
        "project_resolver_model",
        "requirement_reconciler_model",
        "reply_drafter_model",
    )
    @classmethod
    def reject_blank_ai_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("AI model name must not be blank")
        return value

    @field_validator("drive_root_folder_name", "drive_default_category_folder")
    @classmethod
    def reject_blank_drive_folder_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Drive folder names must not be blank")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
