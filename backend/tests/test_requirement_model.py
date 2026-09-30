from sqlalchemy import Date, Enum

from app.models.enums import RequirementState
from app.models.project import Project
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement


def test_requirement_table_contract() -> None:
    table = Requirement.__table__

    assert table.name == "requirements"
    assert set(table.columns) == {
        table.c.id,
        table.c.project_id,
        table.c.name,
        table.c.description,
        table.c.state,
        table.c.expected_date,
        table.c.created_at,
        table.c.updated_at,
    }
    assert table.c.description.nullable
    assert table.c.expected_date.nullable
    assert isinstance(table.c.expected_date.type, Date)
    assert isinstance(table.c.state.type, Enum)
    assert table.c.state.type.enum_class is RequirementState
    assert table.c.state.default.arg is RequirementState.OPEN
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_requirements_name_not_blank",
    }
    foreign_key = next(iter(table.c.project_id.foreign_keys))
    assert foreign_key.target_fullname == "projects.id"
    assert foreign_key.ondelete == "RESTRICT"
    assert "ix_requirements_project_id" in {index.name for index in table.indexes}
    assert Project.requirements.property.back_populates == "project"
    assert Requirement.project.property.back_populates == "requirements"
