from sqlalchemy import JSON

from app.models.ai_proposal import AIProposal, AIProposalEvidence  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.audit_event import AuditEvent
from app.models.correspondence_event import CorrespondenceEvent  # noqa: F401
from app.models.correspondence_project_link import CorrespondenceProjectLink  # noqa: F401
from app.models.evidence_item import EvidenceItem  # noqa: F401
from app.models.policy_evaluation import PolicyEvaluation, PolicyEvaluationEvidence  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401
from app.models.review_item import ReviewItem, ReviewItemCandidateProject  # noqa: F401
from app.models.state_transition import StateTransition, StateTransitionEvidence  # noqa: F401


def test_audit_event_table_contract() -> None:
    table = AuditEvent.__table__

    assert table.name == "audit_events"
    assert isinstance(table.c.details.type, JSON)
    assert not table.c.details.nullable
    assert table.c.actor_identifier.nullable
    assert all(
        table.c[name].nullable
        for name in (
            "correspondence_event_id",
            "project_id",
            "requirement_id",
            "ai_proposal_id",
            "policy_evaluation_id",
            "state_transition_id",
            "review_item_id",
        )
    )
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_audit_events_event_type_not_blank",
        "ck_audit_events_actor_type_not_blank",
        "ck_audit_events_has_lineage",
    }
    assert {index.name for index in table.indexes} >= {
        "ix_audit_events_project_occurred",
        "ix_audit_events_correspondence_event_id",
        "ix_audit_events_transition_id",
        "ix_audit_events_type_occurred",
    }
    assert all(
        foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys
    )
