from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, PrimaryKeyConstraint, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.ai_proposal import AIProposal
from app.models.enums import PolicyDecision
from app.models.evidence_item import EvidenceItem

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.state_transition import StateTransition


class PolicyEvaluation(Base):
    __tablename__ = "policy_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "ai_proposal_id",
            "policy_version",
            name="uq_policy_evaluations_proposal_version",
        ),
        CheckConstraint(
            "btrim(policy_version) <> ''",
            name="ck_policy_evaluations_version_not_blank",
        ),
        Index("ix_policy_evaluations_decision", "decision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ai_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_proposals.id", ondelete="RESTRICT")
    )
    policy_version: Mapped[str] = mapped_column(String)
    decision: Mapped[PolicyDecision] = mapped_column(
        Enum(
            PolicyDecision,
            name="policy_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    triggered_rule_ids: Mapped[list[str]] = mapped_column(JSON)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ai_proposal: Mapped[AIProposal] = relationship(
        back_populates="policy_evaluations"
    )
    evidence_links: Mapped[list["PolicyEvaluationEvidence"]] = relationship(
        back_populates="policy_evaluation"
    )
    state_transitions: Mapped[list["StateTransition"]] = relationship(
        back_populates="policy_evaluation"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="policy_evaluation"
    )



class PolicyEvaluationEvidence(Base):
    __tablename__ = "policy_evaluation_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(
            "policy_evaluation_id",
            "evidence_item_id",
            name="pk_policy_evaluation_evidence",
        ),
        Index(
            "ix_policy_evaluation_evidence_evidence_item_id",
            "evidence_item_id",
        ),
    )

    policy_evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_evaluations.id", ondelete="RESTRICT")
    )
    evidence_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="RESTRICT")
    )

    policy_evaluation: Mapped[PolicyEvaluation] = relationship(
        back_populates="evidence_links"
    )
    evidence_item: Mapped[EvidenceItem] = relationship(
        back_populates="policy_evaluation_links"
    )
