import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_ROOT = Path(__file__).parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0010_add_reply_draft_proposal_type.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "tracework_reply_drafter_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load reply drafter migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reply_drafter_migration_chains_from_0009_and_leaves_one_head():
    migration = _load_migration()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    assert migration.revision == "0010"
    assert migration.down_revision == "0009"
    assert ScriptDirectory.from_config(config).get_heads() == ["0010"]


def test_reply_drafter_migration_updates_only_the_proposal_type_constraint():
    migration = _load_migration()

    class Operations:
        def __init__(self):
            self.calls = []

        def drop_constraint(self, *args, **kwargs):
            self.calls.append(("drop", args, kwargs))

        def create_check_constraint(self, *args, **kwargs):
            self.calls.append(("create", args, kwargs))

    operations = Operations()
    migration.op = operations
    migration.upgrade()

    assert operations.calls[0] == (
        "drop",
        ("proposal_type", "ai_proposals"),
        {"type_": "check"},
    )
    assert operations.calls[1][0] == "create"
    assert "REPLY_DRAFT" in operations.calls[1][1][2]
