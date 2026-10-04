from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.contracts.project_activity import ProjectActivity
from app.contracts.project_workspace import ProjectSummary, ProjectWorkspace
from app.core.auth import require_authenticated_operator
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.services.project_activity import ProjectActivityError, ProjectActivityService
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
        requirement_repository=RequirementRepository(session),
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
