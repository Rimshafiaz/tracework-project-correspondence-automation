from app.models.project import Project
from app.models.project_contact import ProjectContact


def test_project_contact_table_contract() -> None:
    table = ProjectContact.__table__

    assert table.name == "project_contacts"
    assert set(table.columns) == {
        table.c.id,
        table.c.project_id,
        table.c.email_normalized,
        table.c.display_name,
        table.c.role,
        table.c.is_active,
        table.c.created_at,
        table.c.updated_at,
    }
    assert table.c.role.nullable
    assert all(not column.nullable for column in table.columns if column is not table.c.role)
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_project_contacts_project_email",
        "ck_project_contacts_email_not_blank",
        "ck_project_contacts_name_not_blank",
    }
    foreign_key = next(iter(table.c.project_id.foreign_keys))
    assert foreign_key.target_fullname == "projects.id"
    assert foreign_key.ondelete == "RESTRICT"
    assert "ix_project_contacts_email_normalized" in {
        index.name for index in table.indexes
    }
    assert Project.contacts.property.back_populates == "project"
    assert ProjectContact.project.property.back_populates == "contacts"
