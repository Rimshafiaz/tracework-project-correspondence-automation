from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_gmail_is_optional_by_default() -> None:
    settings = Settings(database_url="postgresql+psycopg://example", _env_file=None)

    assert settings.gmail_enabled is False
    assert settings.gmail_account_email is None
    assert settings.gmail_credentials_path == Path(
        ".secrets/gmail/credentials.json"
    )
    assert settings.gmail_token_path == Path(".secrets/gmail/token.json")


def test_enabled_gmail_requires_account_label_and_epoch_boundary() -> None:
    with pytest.raises(ValidationError, match="GMAIL_ACCOUNT_EMAIL"):
        Settings(
            database_url="postgresql+psycopg://example",
            gmail_enabled=True,
            _env_file=None,
        )


def test_enabled_gmail_accepts_complete_configuration() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://example",
        gmail_enabled=True,
        gmail_account_email="tracework@example.com",
        gmail_label_id="Label_123",
        gmail_initial_after_epoch_seconds=1790838000,
        _env_file=None,
    )

    assert settings.gmail_label_id == "Label_123"
    assert settings.gmail_initial_after_epoch_seconds == 1790838000


def test_epoch_boundary_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="must be nonnegative"):
        Settings(
            database_url="postgresql+psycopg://example",
            gmail_enabled=True,
            gmail_account_email="tracework@example.com",
            gmail_label_id="Label_123",
            gmail_initial_after_epoch_seconds=-1,
            _env_file=None,
        )
