from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.project_setup import ProjectSetupRequest
from app.core.auth import AuthenticatedOperator
from app.models.enums import RequirementState
from app.normalization.correspondence import normalize_email
from app.normalization.project_identity import (
    normalize_identifier,
    normalize_identifier_type,
    normalize_project_name,
)
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.services.follow_up_lifecycle import FollowUpLifecycleService

PROJECT_CREATED_AUDIT_EVENT = "project_created"
PROJECT_IDENTIFIER_ADDED_AUDIT_EVENT = "project_identifier_added"
PROJECT_CONTACT_ADDED_AUDIT_EVENT = "project_contact_added"
REQUIREMENT_INITIALIZED_AUDIT_EVENT = "requirement_initialized"


class ProjectSetupConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectSetupResult:
    project_id: UUID


class ProjectSetupService:
    def __init__(
        self,
        *,
        session: Session,
        project_repository: ProjectRepository,
        identifier_repository: ProjectIdentifierRepository,
        contact_repository: ProjectContactRepository,
        requirement_repository: RequirementRepository,
        audit_repository: LineageRepository,
        follow_up_lifecycle_service: FollowUpLifecycleService,
    ) -> None:
        repositories = (
            project_repository,
            identifier_repository,
            contact_repository,
            requirement_repository,
            audit_repository,
        )
        if any(repository.session is not session for repository in repositories):
            raise ValueError("project setup repositories must share one session")
        self.session = session
        self.projects = project_repository
        self.identifiers = identifier_repository
        self.contacts = contact_repository
        self.requirements = requirement_repository
        self.audit = audit_repository
        if follow_up_lifecycle_service.session is not session:
            raise ValueError("project setup services must share one session")
        self.follow_up_lifecycle = follow_up_lifecycle_service

    def create(
        self,
        request: ProjectSetupRequest,
        *,
        operator: AuthenticatedOperator,
    ) -> ProjectSetupResult:
        try:
            project_code = self.projects.allocate_project_code()
            project = self.projects.create(
                project_code=project_code,
                name=request.name.strip(),
                normalized_name=normalize_project_name(request.name),
            )
            self._audit(
                event_type=PROJECT_CREATED_AUDIT_EVENT,
                operator=operator,
                project_id=project.id,
                details={
                    "project_id": str(project.id),
                    "project_code": project.project_code,
                    "name": project.name,
                    "status": project.status.value,
                },
            )

            for item in request.identifiers:
                identifier_type = normalize_identifier_type(item.identifier_type)
                identifier = self.identifiers.create(
                    project_id=project.id,
                    identifier_type=identifier_type,
                    display_value=item.display_value,
                    normalized_value=normalize_identifier(
                        identifier_type,
                        item.display_value,
                    ),
                    verified=True,
                )
                self._audit(
                    event_type=PROJECT_IDENTIFIER_ADDED_AUDIT_EVENT,
                    operator=operator,
                    project_id=project.id,
                    details={
                        "project_identifier_id": str(identifier.id),
                        "identifier_type": identifier.identifier_type,
                        "display_value": identifier.display_value,
                        "verified": True,
                    },
                )

            for item in request.contacts:
                contact = self.contacts.create(
                    project_id=project.id,
                    email_normalized=normalize_email(str(item.email)),
                    display_name=item.display_name,
                    role=item.role,
                )
                self._audit(
                    event_type=PROJECT_CONTACT_ADDED_AUDIT_EVENT,
                    operator=operator,
                    project_id=project.id,
                    details={
                        "project_contact_id": str(contact.id),
                        "email": contact.email_normalized,
                        "display_name": contact.display_name,
                        "role": contact.role,
                        "is_active": True,
                    },
                )

            for item in request.requirements:
                requirement = self.requirements.create(
                    project_id=project.id,
                    name=item.name,
                    description=item.description,
                    expected_date=item.expected_date,
                )
                setup_audit = self._audit(
                    event_type=REQUIREMENT_INITIALIZED_AUDIT_EVENT,
                    operator=operator,
                    project_id=project.id,
                    requirement_id=requirement.id,
                    details={
                        "requirement_id": str(requirement.id),
                        "name": requirement.name,
                        "state": RequirementState.OPEN.value,
                        "expected_date": (
                            requirement.expected_date.isoformat()
                            if requirement.expected_date is not None
                            else None
                        ),
                    },
                )
                self.follow_up_lifecycle.reconcile(
                    requirement.id,
                    originating_audit_event_id=setup_audit.id,
                    actor_type="authenticated_operator",
                    actor_identifier=operator.subject,
                )

            self.session.commit()
            return ProjectSetupResult(project_id=project.id)
        except ProjectSetupConflictError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ProjectSetupConflictError(
                "project setup conflicts with existing configuration"
            ) from exc
        except Exception:
            self.session.rollback()
            raise

    def _audit(
        self,
        *,
        event_type: str,
        operator: AuthenticatedOperator,
        project_id: UUID,
        details: dict[str, object],
        requirement_id: UUID | None = None,
    ):
        return self.audit.create_audit_event(
            event_type=event_type,
            actor_type="authenticated_operator",
            actor_identifier=operator.subject,
            project_id=project_id,
            requirement_id=requirement_id,
            details=details,
        )
