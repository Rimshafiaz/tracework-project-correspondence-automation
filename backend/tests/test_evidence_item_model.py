from sqlalchemy import Enum, JSON

from app.models.attachment import Attachment
from app.models.correspondence_event import CorrespondenceEvent
from app.models.correspondence_project_link import CorrespondenceProjectLink  # noqa: F401
from app.models.enums import EvidenceValidity
from app.models.evidence_item import EvidenceItem
from app.models.project import Project
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement


def test_evidence_item_table_contract() -> None:
    table = EvidenceItem.__table__

    assert table.name == "evidence_items"
    assert table.c.attachment_id.nullable
    assert table.c.project_id.nullable
    assert table.c.requirement_id.nullable
    assert table.c.page_number.nullable
    assert table.c.section.nullable
    assert table.c.normalized_value.nullable
    assert table.c.provenance_metadata.nullable
    assert isinstance(table.c.provenance_metadata.type, JSON)
    assert isinstance(table.c.validity.type, Enum)
    assert table.c.validity.type.enum_class is EvidenceValidity
    assert table.c.validity.default.arg is EvidenceValidity.VALID
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_evidence_items_source_type_not_blank",
        "ck_evidence_items_excerpt_not_blank",
        "ck_evidence_items_page_number_positive",
        "ck_evidence_items_invalidation_complete",
    }
    assert {index.name for index in table.indexes} >= {
        "ix_evidence_items_correspondence_event_id",
        "ix_evidence_items_attachment_id",
        "ix_evidence_items_project_id",
        "ix_evidence_items_requirement_validity",
    }
    assert CorrespondenceEvent.evidence_items.property.back_populates == (
        "correspondence_event"
    )
    assert Attachment.evidence_items.property.back_populates == "attachment"
    assert Project.evidence_items.property.back_populates == "project"
    assert Requirement.evidence_items.property.back_populates == "requirement"
