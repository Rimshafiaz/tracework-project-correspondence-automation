from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, PrimaryKeyConstraint, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import ProposalType
from app.models.evidence_item import EvidenceItem

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.policy_evaluation import PolicyEvaluation
    from app.models.state_transition import StateTransition


class AIProposal(Base):
    __tablename__ = "ai_proposals"
    __table_args__ = (
        CheckConstraint(
            "btrim(model_identifier) <> ''",
            name="ck_ai_proposals_model_identifier_not_blank",
        ),
        CheckConstraint(
            "btrim(prompt_version) <> ''",
            name="ck_ai_proposals_prompt_version_not_blank",
        ),
        CheckConstraint(
            "btrim(input_hash) <> ''",
            name="ck_ai_proposals_input_hash_not_blank",
        ),
        Index(
            "ix_ai_proposals_event_type",
            "correspondence_event_id",
            "proposal_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correspondence_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    proposal_type: Mapped[ProposalType] = mapped_column(
        Enum(
            ProposalType,
            name="proposal_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    model_identifier: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    input_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    structured_output: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    correspondence_event: Mapped[CorrespondenceEvent] = relationship(
        back_populates="ai_proposals"
    )
    evidence_links: Mapped[list["AIProposalEvidence"]] = relationship(
        back_populates="ai_proposal"
    )
    policy_evaluations: Mapped[list["PolicyEvaluation"]] = relationship(
        back_populates="ai_proposal"
    )
    state_transitions: Mapped[list["StateTransition"]] = relationship(
        back_populates="ai_proposal"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="ai_proposal"
    )


class AIProposalEvidence(Base):
    __tablename__ = "ai_proposal_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(
            "ai_proposal_id",
            "evidence_item_id",
            name="pk_ai_proposal_evidence",
        ),
        Index("ix_ai_proposal_evidence_evidence_item_id", "evidence_item_id"),
    )

    ai_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_proposals.id", ondelete="RESTRICT")
    )
    evidence_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="RESTRICT")
    )

    ai_proposal: Mapped[AIProposal] = relationship(back_populates="evidence_links")
    evidence_item: Mapped[EvidenceItem] = relationship(back_populates="proposal_links")
