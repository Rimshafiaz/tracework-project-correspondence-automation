from sqlalchemy import Enum, Uuid

from app.models.enums import ProjectStatus
from app.models.project import Project


def test_project_table_contract() -> None:
    table = Project.__table__

    assert table.name == "projects"
    assert set(table.columns) == {
        table.c.id,
        table.c.project_code,
        table.c.name,
        table.c.normalized_name,
        table.c.status,
        table.c.created_at,
        table.c.updated_at,
    }
    assert isinstance(table.c.id.type, Uuid)
    assert table.c.id.primary_key
    assert isinstance(table.c.status.type, Enum)
    assert table.c.status.type.enum_class is ProjectStatus
    assert not any(column.nullable for column in table.columns)
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_projects_code_not_blank",
        "ck_projects_name_not_blank",
        "ck_projects_normalized_name_not_blank",
        "uq_projects_project_code",
    }
    assert "ix_projects_normalized_name" in {index.name for index in table.indexes}
