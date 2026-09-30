from sqlalchemy import Enum, JSON

from app.models.ai_proposal import AIProposal, AIProposalEvidence
from app.models.attachment import Attachment  # noqa: F401
from app.models.correspondence_event import CorrespondenceEvent
from app.models.correspondence_project_link import CorrespondenceProjectLink  # noqa: F401
from app.models.enums import ProposalType
from app.models.evidence_item import EvidenceItem
from app.models.project import Project  # noqa: F401
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401


def test_ai_proposal_table_contract() -> None:
    table = AIProposal.__table__

    assert table.name == "ai_proposals"
    assert isinstance(table.c.proposal_type.type, Enum)
    assert table.c.proposal_type.type.enum_class is ProposalType
    assert isinstance(table.c.input_metadata.type, JSON)
    assert table.c.input_metadata.nullable
    assert isinstance(table.c.structured_output.type, JSON)
    assert not table.c.structured_output.nullable
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_ai_proposals_model_identifier_not_blank",
        "ck_ai_proposals_prompt_version_not_blank",
        "ck_ai_proposals_input_hash_not_blank",
    }
    event_fk = next(iter(table.c.correspondence_event_id.foreign_keys))
    assert event_fk.target_fullname == "correspondence_events.id"
    assert event_fk.ondelete == "RESTRICT"
    assert "ix_ai_proposals_event_type" in {index.name for index in table.indexes}


def test_ai_proposal_evidence_link_contract() -> None:
    table = AIProposalEvidence.__table__

    assert table.name == "ai_proposal_evidence"
    assert {column.name for column in table.primary_key.columns} == {
        "ai_proposal_id",
        "evidence_item_id",
    }
    assert all(
        foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys
    )
    assert AIProposal.evidence_links.property.back_populates == "ai_proposal"
    assert EvidenceItem.proposal_links.property.back_populates == "evidence_item"
    assert CorrespondenceEvent.ai_proposals.property.back_populates == (
        "correspondence_event"
    )
