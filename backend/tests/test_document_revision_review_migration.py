import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_ROOT = Path(__file__).parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "0007_add_document_revision_review_type.py"
)


def test_document_revision_review_migration_chains_from_0006() -> None:
    spec = importlib.util.spec_from_file_location(
        "tracework_document_revision_review_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load document revision review migration")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    assert migration.revision == "0007"
    assert migration.down_revision == "0006"
    assert ScriptDirectory.from_config(config).get_heads() == ["0010"]
