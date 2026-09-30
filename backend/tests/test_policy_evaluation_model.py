from sqlalchemy import Enum, JSON

from app.models.ai_proposal import AIProposal, AIProposalEvidence  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.correspondence_event import CorrespondenceEvent  # noqa: F401
from app.models.correspondence_project_link import CorrespondenceProjectLink  # noqa: F401
from app.models.enums import PolicyDecision
from app.models.evidence_item import EvidenceItem
from app.models.policy_evaluation import PolicyEvaluation, PolicyEvaluationEvidence
from app.models.project import Project  # noqa: F401
from app.models.project_contact import ProjectContact  # noqa: F401
from app.models.project_identifier import ProjectIdentifier  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401


def test_policy_evaluation_table_contract() -> None:
    table = PolicyEvaluation.__table__

    assert table.name == "policy_evaluations"
    assert isinstance(table.c.decision.type, Enum)
    assert table.c.decision.type.enum_class is PolicyDecision
    assert isinstance(table.c.triggered_rule_ids.type, JSON)
    assert isinstance(table.c.reasons.type, JSON)
    assert not table.c.triggered_rule_ids.nullable
    assert not table.c.reasons.nullable
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_policy_evaluations_proposal_version",
        "ck_policy_evaluations_version_not_blank",
    }
    proposal_fk = next(iter(table.c.ai_proposal_id.foreign_keys))
    assert proposal_fk.target_fullname == "ai_proposals.id"
    assert proposal_fk.ondelete == "RESTRICT"
    assert "ix_policy_evaluations_decision" in {
        index.name for index in table.indexes
    }


def test_policy_evaluation_evidence_link_contract() -> None:
    table = PolicyEvaluationEvidence.__table__

    assert table.name == "policy_evaluation_evidence"
    assert {column.name for column in table.primary_key.columns} == {
        "policy_evaluation_id",
        "evidence_item_id",
    }
    assert all(
        foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys
    )
    assert PolicyEvaluation.ai_proposal.property.back_populates == (
        "policy_evaluations"
    )
    assert PolicyEvaluation.evidence_links.property.back_populates == (
        "policy_evaluation"
    )
    assert EvidenceItem.policy_evaluation_links.property.back_populates == (
        "evidence_item"
    )
