from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.ai_proposal import AIProposal
from app.models.correspondence_event import CorrespondenceEvent
from app.models.policy_evaluation import PolicyEvaluation
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.review_item import ReviewItem
from app.models.state_transition import StateTransition


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "btrim(event_type) <> ''",
            name="ck_audit_events_event_type_not_blank",
        ),
        CheckConstraint(
            "btrim(actor_type) <> ''",
            name="ck_audit_events_actor_type_not_blank",
        ),
        CheckConstraint(
            "correspondence_event_id IS NOT NULL OR project_id IS NOT NULL OR "
            "requirement_id IS NOT NULL OR ai_proposal_id IS NOT NULL OR "
            "policy_evaluation_id IS NOT NULL OR state_transition_id IS NOT NULL OR "
            "review_item_id IS NOT NULL",
            name="ck_audit_events_has_lineage",
        ),
        Index("ix_audit_events_project_occurred", "project_id", "occurred_at"),
        Index(
            "ix_audit_events_correspondence_event_id",
            "correspondence_event_id",
        ),
        Index("ix_audit_events_transition_id", "state_transition_id"),
        Index("ix_audit_events_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String)
    actor_type: Mapped[str] = mapped_column(String)
    actor_identifier: Mapped[str | None] = mapped_column(String)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    correspondence_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("correspondence_events.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    requirement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    ai_proposal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_proposals.id", ondelete="RESTRICT")
    )
    policy_evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_evaluations.id", ondelete="RESTRICT")
    )
    state_transition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("state_transitions.id", ondelete="RESTRICT")
    )
    review_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("review_items.id", ondelete="RESTRICT")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    correspondence_event: Mapped[CorrespondenceEvent | None] = relationship(
        back_populates="audit_events"
    )
    project: Mapped[Project | None] = relationship(back_populates="audit_events")
    requirement: Mapped[Requirement | None] = relationship(back_populates="audit_events")
    ai_proposal: Mapped[AIProposal | None] = relationship(back_populates="audit_events")
    policy_evaluation: Mapped[PolicyEvaluation | None] = relationship(
        back_populates="audit_events"
    )
    state_transition: Mapped[StateTransition | None] = relationship(
        back_populates="audit_events"
    )
    review_item: Mapped[ReviewItem | None] = relationship(back_populates="audit_events")

