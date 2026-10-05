import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repositories.project import ProjectRepository


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0004_create_project_code_sequence.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "tracework_project_code_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load project code migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("sequence_value", "expected"),
    [(1, "TW-001"), (42, "TW-042"), (999, "TW-999"), (1000, "TW-1000")],
)
def test_repository_formats_sequence_values_without_truncation(
    sequence_value: int,
    expected: str,
) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = sequence_value

    result = ProjectRepository(session).allocate_project_code()

    assert result == expected


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured",
)
def test_migration_initializes_above_existing_tw_codes_without_changing_rows() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    schema_name = "test_project_code_migration"
    migration = _load_migration()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema_name}"'))
            connection.execute(text("CREATE TABLE projects (project_code TEXT NOT NULL)"))
            connection.execute(
                text(
                    "INSERT INTO projects (project_code) VALUES "
                    "('LEGACY-A'), ('TW-009'), ('TW-1200')"
                )
            )
            migration.op = Operations(MigrationContext.configure(connection))

            migration.upgrade()

            assert connection.scalar(
                text("SELECT nextval('tracework_project_code_seq')")
            ) == 1201
            assert connection.scalars(
                text("SELECT project_code FROM projects ORDER BY project_code")
            ).all() == ["LEGACY-A", "TW-009", "TW-1200"]
        finally:
            transaction.rollback()
            engine.dispose()


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured",
)
def test_generated_codes_are_unique_under_postgresql_concurrency() -> None:
    engine = create_engine(TEST_DATABASE_URL)

    def allocate() -> str:
        with Session(engine) as session:
            return ProjectRepository(session).allocate_project_code()

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            codes = list(executor.map(lambda _: allocate(), range(24)))
    finally:
        engine.dispose()

    assert len(codes) == len(set(codes))
    assert all(code.startswith("TW-") for code in codes)
