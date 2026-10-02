import pytest
from pydantic import ValidationError

from app.core.config import Settings

DATABASE_URL = "postgresql+psycopg://test:test@localhost/test"


def test_extraction_limits_match_the_approved_defaults() -> None:
    settings = Settings(database_url=DATABASE_URL)

    assert settings.attachment_max_size_bytes == 26_214_400
    assert settings.pdf_max_pages == 250
    assert settings.extraction_max_characters == 1_000_000
    assert settings.docx_max_paragraphs == 10_000
    assert settings.docx_max_tables == 500
    assert settings.docx_max_table_cells == 50_000


def test_extraction_limits_can_be_overridden() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        attachment_max_size_bytes=1024,
        pdf_max_pages=10,
        extraction_max_characters=5000,
        docx_max_paragraphs=100,
        docx_max_tables=20,
        docx_max_table_cells=200,
    )

    assert settings.attachment_max_size_bytes == 1024
    assert settings.pdf_max_pages == 10
    assert settings.extraction_max_characters == 5000
    assert settings.docx_max_paragraphs == 100
    assert settings.docx_max_tables == 20
    assert settings.docx_max_table_cells == 200


@pytest.mark.parametrize(
    "field",
    [
        "attachment_max_size_bytes",
        "pdf_max_pages",
        "extraction_max_characters",
        "docx_max_paragraphs",
        "docx_max_tables",
        "docx_max_table_cells",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_extraction_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, **{field: value})


def test_invalid_extraction_limit_string_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, pdf_max_pages="invalid")


def test_project_resolver_model_is_configurable_and_non_blank() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        project_resolver_model=" gemini-example ",
    )

    assert settings.project_resolver_model == "gemini-example"
    with pytest.raises(ValidationError, match="must not be blank"):
        Settings(database_url=DATABASE_URL, project_resolver_model=" ")
