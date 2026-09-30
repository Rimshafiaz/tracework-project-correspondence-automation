from sqlalchemy import Enum, JSON

from app.models.ai_proposal import AIProposal, AIProposalEvidence  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.correspondence_event import CorrespondenceEvent  # noqa: F401
from app.models.correspondence_project_link import CorrespondenceProjectLink  # noqa: F401
from app.models.enums import TransitionDisposition, TransitionStatus
from app.models.evidence_item import EvidenceItem
from app.models.policy_evaluation import PolicyEvaluation, PolicyEvaluationEvidence  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401
from app.models.state_transition import StateTransition, StateTransitionEvidence


def test_state_transition_table_contract() -> None:
    table = StateTransition.__table__

    assert table.name == "state_transitions"
    assert isinstance(table.c.current_state.type, JSON)
    assert isinstance(table.c.proposed_state.type, JSON)
    assert isinstance(table.c.requirement_effects.type, JSON)
    assert isinstance(table.c.document_effects.type, JSON)
    assert isinstance(table.c.follow_up_effects.type, JSON)
    assert isinstance(table.c.disposition.type, Enum)
    assert table.c.disposition.type.enum_class is TransitionDisposition
    assert isinstance(table.c.status.type, Enum)
    assert table.c.status.type.enum_class is TransitionStatus
    assert table.c.status.default.arg is TransitionStatus.PREVIEWED
    assert table.c.applied_at.nullable
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_state_transitions_policy_entity",
        "ck_state_transitions_entity_type_not_blank",
        "ck_state_transitions_applied_at_matches_status",
    }
    assert {index.name for index in table.indexes} >= {
        "ix_state_transitions_affected_entity",
        "ix_state_transitions_status",
    }
    assert all(
        foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys
    )


def test_state_transition_evidence_link_contract() -> None:
    table = StateTransitionEvidence.__table__

    assert table.name == "state_transition_evidence"
    assert {column.name for column in table.primary_key.columns} == {
        "state_transition_id",
        "evidence_item_id",
    }
    assert StateTransition.ai_proposal.property.back_populates == (
        "state_transitions"
    )
    assert StateTransition.policy_evaluation.property.back_populates == (
        "state_transitions"
    )
    assert EvidenceItem.state_transition_links.property.back_populates == (
        "evidence_item"
    )
