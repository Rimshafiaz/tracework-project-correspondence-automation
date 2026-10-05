from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.contracts.project_activity import ProjectActivity
from app.contracts.project_setup import ProjectSetupRequest
from app.contracts.project_workspace import ProjectSummary, ProjectWorkspace
from app.core.auth import AuthenticatedOperator, require_authenticated_operator
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.services.project_activity import ProjectActivityError, ProjectActivityService
from app.services.project_setup import ProjectSetupConflictError, ProjectSetupService
from app.services.project_workspace import (
    ProjectWorkspaceNotFoundError,
    ProjectWorkspaceService,
)

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(require_authenticated_operator)],
)


def get_project_workspace_service(
    session: Session = Depends(get_session),
) -> ProjectWorkspaceService:
    return ProjectWorkspaceService(
        project_repository=ProjectRepository(session),
        identifier_repository=ProjectIdentifierRepository(session),
        contact_repository=ProjectContactRepository(session),
        requirement_repository=RequirementRepository(session),
    )


def get_project_setup_service(
    session: Session = Depends(get_session),
) -> ProjectSetupService:
    return ProjectSetupService(
        session=session,
        project_repository=ProjectRepository(session),
        identifier_repository=ProjectIdentifierRepository(session),
        contact_repository=ProjectContactRepository(session),
        requirement_repository=RequirementRepository(session),
        audit_repository=LineageRepository(session),
    )


def get_project_activity_service(
    session: Session = Depends(get_session),
) -> ProjectActivityService:
    return ProjectActivityService(
        project_repository=ProjectRepository(session),
        lineage_repository=LineageRepository(session),
    )


@router.get("", response_model=list[ProjectSummary])
def list_projects(
    service: ProjectWorkspaceService = Depends(get_project_workspace_service),
) -> tuple[ProjectSummary, ...]:
    return service.list_projects()


@router.post("", response_model=ProjectWorkspace, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectSetupRequest,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    setup_service: ProjectSetupService = Depends(get_project_setup_service),
    workspace_service: ProjectWorkspaceService = Depends(
        get_project_workspace_service
    ),
) -> ProjectWorkspace:
    try:
        result = setup_service.create(request, operator=operator)
    except ProjectSetupConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project setup conflicts with existing configuration",
        ) from exc
    return workspace_service.get_workspace(result.project_id)


@router.get("/{project_id}", response_model=ProjectWorkspace)
def get_project_workspace(
    project_id: UUID,
    service: ProjectWorkspaceService = Depends(get_project_workspace_service),
) -> ProjectWorkspace:
    try:
        return service.get_workspace(project_id)
    except ProjectWorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project was not found",
        ) from exc


@router.get("/{project_id}/activity", response_model=ProjectActivity)
def get_project_activity(
    project_id: UUID,
    service: ProjectActivityService = Depends(get_project_activity_service),
) -> ProjectActivity:
    try:
        return service.load(project_id)
    except ProjectActivityError as exc:
        if str(exc) == "project was not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project was not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project activity history is inconsistent",
        ) from exc
