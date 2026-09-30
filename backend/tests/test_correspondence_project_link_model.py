from app.models.correspondence_event import CorrespondenceEvent
from app.models.correspondence_project_link import CorrespondenceProjectLink
from app.models.project import Project
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401


def test_correspondence_project_link_table_contract() -> None:
    table = CorrespondenceProjectLink.__table__

    assert table.name == "correspondence_project_links"
    assert set(table.columns) == {
        table.c.id,
        table.c.correspondence_event_id,
        table.c.project_id,
        table.c.created_at,
    }
    assert all(not column.nullable for column in table.columns)
    assert "uq_correspondence_project_links_event_project" in {
        constraint.name for constraint in table.constraints
    }
    event_fk = next(iter(table.c.correspondence_event_id.foreign_keys))
    project_fk = next(iter(table.c.project_id.foreign_keys))
    assert event_fk.target_fullname == "correspondence_events.id"
    assert project_fk.target_fullname == "projects.id"
    assert event_fk.ondelete == project_fk.ondelete == "RESTRICT"
    assert "ix_correspondence_project_links_project_id" in {
        index.name for index in table.indexes
    }
    assert CorrespondenceEvent.project_links.property.back_populates == (
        "correspondence_event"
    )
    assert Project.correspondence_links.property.back_populates == "project"
