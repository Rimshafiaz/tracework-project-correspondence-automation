from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ProjectStatus

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.project_contact import ProjectContact
    from app.models.project_identifier import ProjectIdentifier
    from app.models.requirement import Requirement
    from app.models.correspondence_project_link import CorrespondenceProjectLink
    from app.models.evidence_item import EvidenceItem
    from app.models.document import Document
    from app.models.follow_up import FollowUp
    from app.models.review_item import ReviewItemCandidateProject


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("project_code", name="uq_projects_project_code"),
        CheckConstraint("btrim(project_code) <> ''", name="ck_projects_code_not_blank"),
        CheckConstraint("btrim(name) <> ''", name="ck_projects_name_not_blank"),
        CheckConstraint(
            "btrim(normalized_name) <> ''",
            name="ck_projects_normalized_name_not_blank",
        ),
        Index("ix_projects_normalized_name", "normalized_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_code: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    normalized_name: Mapped[str] = mapped_column(String)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ProjectStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    contacts: Mapped[list["ProjectContact"]] = relationship(back_populates="project")
    identifiers: Mapped[list["ProjectIdentifier"]] = relationship(
        back_populates="project"
    )
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="project")
    correspondence_links: Mapped[list["CorrespondenceProjectLink"]] = relationship(
        back_populates="project"
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="project"
    )
    review_candidate_links: Mapped[list["ReviewItemCandidateProject"]] = relationship(
        back_populates="project"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="project")
    documents: Mapped[list["Document"]] = relationship(back_populates="project")
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="project")
