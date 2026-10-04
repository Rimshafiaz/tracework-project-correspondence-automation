import pytest
from pydantic import ValidationError

from app.core.config import Settings

DATABASE_URL = "postgresql+psycopg://test:test@localhost/test"


def test_auth_and_cors_configuration_is_normalized() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        supabase_auth_issuer="https://example.supabase.co/auth/v1/",
        supabase_auth_audience=" tracework ",
        cors_allowed_origins=(
            "http://localhost:5173/, https://tracework.example/"
        ),
        _env_file=None,
    )

    assert settings.supabase_auth_issuer == "https://example.supabase.co/auth/v1"
    assert settings.supabase_auth_audience == "tracework"
    assert settings.cors_origins == (
        "http://localhost:5173",
        "https://tracework.example",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("supabase_auth_issuer", "https://example.supabase.co/not-auth"),
        ("supabase_auth_audience", " "),
        ("cors_allowed_origins", "*"),
        ("cors_allowed_origins", "https://tracework.example/path"),
    ],
)
def test_invalid_auth_and_cors_configuration_is_rejected(field, value) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, _env_file=None, **{field: value})


def test_production_requires_auth_issuer() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_AUTH_ISSUER"):
        Settings(
            database_url=DATABASE_URL,
            app_env="production",
            supabase_auth_issuer=None,
            _env_file=None,
        )
