from app.models.project import Project
from app.models.project_identifier import ProjectIdentifier


def test_project_identifier_table_contract() -> None:
    table = ProjectIdentifier.__table__

    assert table.name == "project_identifiers"
    assert set(table.columns) == {
        table.c.id,
        table.c.project_id,
        table.c.identifier_type,
        table.c.display_value,
        table.c.normalized_value,
        table.c.verified,
        table.c.created_at,
        table.c.updated_at,
    }
    assert all(not column.nullable for column in table.columns)
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_project_identifiers_project_type_value",
        "ck_project_identifiers_type_not_blank",
        "ck_project_identifiers_display_value_not_blank",
        "ck_project_identifiers_normalized_value_not_blank",
    }
    foreign_key = next(iter(table.c.project_id.foreign_keys))
    assert foreign_key.target_fullname == "projects.id"
    assert foreign_key.ondelete == "RESTRICT"
    assert "ix_project_identifiers_type_normalized_value" in {
        index.name for index in table.indexes
    }
    assert Project.identifiers.property.back_populates == "project"
    assert ProjectIdentifier.project.property.back_populates == "identifiers"
