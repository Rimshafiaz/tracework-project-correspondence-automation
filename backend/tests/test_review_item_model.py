from sqlalchemy import Enum, JSON

from app.models.ai_proposal import AIProposal, AIProposalEvidence  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.correspondence_event import CorrespondenceEvent
from app.models.correspondence_project_link import CorrespondenceProjectLink  # noqa: F401
from app.models.enums import ReviewStatus, ReviewType
from app.models.evidence_item import EvidenceItem  # noqa: F401
from app.models.policy_evaluation import PolicyEvaluation, PolicyEvaluationEvidence  # noqa: F401
from app.models.project import Project
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401
from app.models.review_item import ReviewItem, ReviewItemCandidateProject
from app.models.state_transition import StateTransition, StateTransitionEvidence  # noqa: F401


def test_review_item_table_contract() -> None:
    table = ReviewItem.__table__

    assert table.name == "review_items"
    assert isinstance(table.c.review_type.type, Enum)
    assert table.c.review_type.type.enum_class is ReviewType
    assert isinstance(table.c.status.type, Enum)
    assert table.c.status.type.enum_class is ReviewStatus
    assert table.c.status.default.arg is ReviewStatus.PENDING
    assert isinstance(table.c.correction_payload.type, JSON)
    assert table.c.correction_payload.nullable
    assert table.c.resolved_at.nullable
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_review_items_state_transition_id",
        "ck_review_items_reason_not_blank",
        "ck_review_items_resolution_matches_status",
    }
    assert {index.name for index in table.indexes} >= {
        "ix_review_items_status_created",
        "ix_review_items_correspondence_event_id",
    }
    assert all(
        foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys
    )
    assert StateTransition.review_item.property.back_populates == "state_transition"
    assert CorrespondenceEvent.review_items.property.back_populates == (
        "correspondence_event"
    )


def test_review_candidate_project_link_contract() -> None:
    table = ReviewItemCandidateProject.__table__

    assert table.name == "review_item_candidate_projects"
    assert {column.name for column in table.primary_key.columns} == {
        "review_item_id",
        "project_id",
    }
    assert all(
        foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys
    )
    assert ReviewItem.candidate_project_links.property.back_populates == "review_item"
    assert Project.review_candidate_links.property.back_populates == "project"
