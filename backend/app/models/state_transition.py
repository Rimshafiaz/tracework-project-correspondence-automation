from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, JSON, PrimaryKeyConstraint, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.ai_proposal import AIProposal
from app.models.enums import TransitionDisposition, TransitionStatus
from app.models.evidence_item import EvidenceItem
from app.models.policy_evaluation import PolicyEvaluation

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.review_item import ReviewItem


class StateTransition(Base):
    __tablename__ = "state_transitions"
    __table_args__ = (
        UniqueConstraint(
            "policy_evaluation_id",
            "affected_entity_type",
            "affected_entity_id",
            name="uq_state_transitions_policy_entity",
        ),
        CheckConstraint(
            "btrim(affected_entity_type) <> ''",
            name="ck_state_transitions_entity_type_not_blank",
        ),
        CheckConstraint(
            "(status = 'APPLIED' AND applied_at IS NOT NULL) OR "
            "(status <> 'APPLIED' AND applied_at IS NULL)",
            name="ck_state_transitions_applied_at_matches_status",
        ),
        Index(
            "ix_state_transitions_affected_entity",
            "affected_entity_type",
            "affected_entity_id",
        ),
        Index("ix_state_transitions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ai_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_proposals.id", ondelete="RESTRICT")
    )
    policy_evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_evaluations.id", ondelete="RESTRICT")
    )
    affected_entity_type: Mapped[str] = mapped_column(String)
    affected_entity_id: Mapped[UUID] = mapped_column(Uuid)
    current_state: Mapped[dict[str, object]] = mapped_column(JSON)
    proposed_state: Mapped[dict[str, object]] = mapped_column(JSON)
    requirement_effects: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    document_effects: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    follow_up_effects: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    disposition: Mapped[TransitionDisposition] = mapped_column(
        Enum(
            TransitionDisposition,
            name="transition_disposition",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    status: Mapped[TransitionStatus] = mapped_column(
        Enum(
            TransitionStatus,
            name="transition_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=TransitionStatus.PREVIEWED,
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ai_proposal: Mapped[AIProposal] = relationship(
        back_populates="state_transitions"
    )
    policy_evaluation: Mapped[PolicyEvaluation] = relationship(
        back_populates="state_transitions"
    )
    evidence_links: Mapped[list["StateTransitionEvidence"]] = relationship(
        back_populates="state_transition"
    )
    review_item: Mapped["ReviewItem | None"] = relationship(
        back_populates="state_transition"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="state_transition"
    )




class StateTransitionEvidence(Base):
    __tablename__ = "state_transition_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(
            "state_transition_id",
            "evidence_item_id",
            name="pk_state_transition_evidence",
        ),
        Index(
            "ix_state_transition_evidence_evidence_item_id",
            "evidence_item_id",
        ),
    )

    state_transition_id: Mapped[UUID] = mapped_column(
        ForeignKey("state_transitions.id", ondelete="RESTRICT")
    )
    evidence_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="RESTRICT")
    )

    state_transition: Mapped[StateTransition] = relationship(
        back_populates="evidence_links"
    )
    evidence_item: Mapped[EvidenceItem] = relationship(
        back_populates="state_transition_links"
    )
