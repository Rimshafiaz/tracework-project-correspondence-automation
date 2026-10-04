from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewApproval,
    ProjectResolutionReviewAssignmentRequest,
    ProjectResolutionReviewDecisionContext,
    ProjectResolutionReviewDecisionResponse,
    ProjectResolutionReviewDetail,
    ProjectResolutionReviewRequest,
    ProjectResolutionReviewReplacementAssignment,
    ProjectResolutionReviewSummary,
    ReviewActor,
)
from app.core.auth import AuthenticatedOperator, require_authenticated_operator
from app.db.session import SessionLocal
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import (
    CorrespondenceProjectLinkRepository,
)
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.project_resolution_review_decision import (
    ProjectResolutionReviewDecisionError,
    ProjectResolutionReviewDecisionService,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryError,
    ProjectResolutionReviewQueryService,
)

router = APIRouter(
    prefix="/reviews/project-resolution",
    tags=["reviews"],
    dependencies=[Depends(require_authenticated_operator)],
)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_review_query_service(
    session: Session = Depends(get_session),
) -> ProjectResolutionReviewQueryService:
    return ProjectResolutionReviewQueryService(
        review_repository=ReviewItemRepository(session),
        correspondence_repository=CorrespondenceEventRepository(session),
        lineage_repository=LineageRepository(session),
    )


def get_review_decision_service(
    session: Session = Depends(get_session),
) -> ProjectResolutionReviewDecisionService:
    return ProjectResolutionReviewDecisionService(
        session=session,
        review_repository=ReviewItemRepository(session),
        lineage_repository=LineageRepository(session),
        project_repository=ProjectRepository(session),
        project_link_repository=CorrespondenceProjectLinkRepository(session),
    )


@router.get("", response_model=list[ProjectResolutionReviewSummary])
def list_open_project_resolution_reviews(
    service: ProjectResolutionReviewQueryService = Depends(
        get_review_query_service
    ),
) -> tuple[ProjectResolutionReviewSummary, ...]:
    return service.list_open()


@router.get("/{review_item_id}", response_model=ProjectResolutionReviewDetail)
def get_project_resolution_review(
    review_item_id: UUID,
    service: ProjectResolutionReviewQueryService = Depends(
        get_review_query_service
    ),
) -> ProjectResolutionReviewDetail:
    try:
        return service.get_detail(review_item_id)
    except ProjectResolutionReviewQueryError as exc:
        raise _query_http_error(exc) from exc


@router.post(
    "/{review_item_id}/approve",
    response_model=ProjectResolutionReviewDecisionResponse,
)
def approve_project_resolution_review(
    review_item_id: UUID,
    request: ProjectResolutionReviewRequest,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ProjectResolutionReviewDecisionService = Depends(
        get_review_decision_service
    ),
) -> ProjectResolutionReviewDecisionResponse:
    try:
        result = service.approve(
            review_item_id,
            ProjectResolutionReviewApproval(
                actor=_authenticated_actor(operator),
                comment=request.comment,
            ),
        )
        return _decision_response(result)
    except ProjectResolutionReviewDecisionError as exc:
        raise _decision_http_error(exc) from exc


@router.post(
    "/{review_item_id}/assign",
    response_model=ProjectResolutionReviewDecisionResponse,
)
def assign_project_resolution_review(
    review_item_id: UUID,
    request: ProjectResolutionReviewAssignmentRequest,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ProjectResolutionReviewDecisionService = Depends(
        get_review_decision_service
    ),
) -> ProjectResolutionReviewDecisionResponse:
    try:
        result = service.assign_or_correct(
            review_item_id,
            ProjectResolutionReviewReplacementAssignment(
                actor=_authenticated_actor(operator),
                comment=request.comment,
                project_ids=request.project_ids,
            ),
        )
        return _decision_response(result)
    except ProjectResolutionReviewDecisionError as exc:
        raise _decision_http_error(exc) from exc


@router.post(
    "/{review_item_id}/reject",
    response_model=ProjectResolutionReviewDecisionResponse,
)
def reject_project_resolution_review(
    review_item_id: UUID,
    request: ProjectResolutionReviewRequest,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ProjectResolutionReviewDecisionService = Depends(
        get_review_decision_service
    ),
) -> ProjectResolutionReviewDecisionResponse:
    try:
        result = service.reject(
            review_item_id,
            ProjectResolutionReviewDecisionContext(
                actor=_authenticated_actor(operator),
                comment=request.comment,
            ),
        )
        return _decision_response(result)
    except ProjectResolutionReviewDecisionError as exc:
        raise _decision_http_error(exc) from exc


def _authenticated_actor(operator: AuthenticatedOperator) -> ReviewActor:
    return ReviewActor(
        actor_type="authenticated_operator",
        actor_identifier=operator.subject,
    )


def _decision_response(result) -> ProjectResolutionReviewDecisionResponse:
    return ProjectResolutionReviewDecisionResponse(
        review_item_id=result.review_item.id,
        status=result.review_item.status,
        action=result.action,
        project_ids=tuple(link.project_id for link in result.project_links),
        project_link_ids=tuple(link.id for link in result.project_links),
        idempotent_replay=result.idempotent_replay,
    )


def _query_http_error(error: ProjectResolutionReviewQueryError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if "not found" in str(error)
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=code, detail=str(error))


def _decision_http_error(
    error: ProjectResolutionReviewDecisionError,
) -> HTTPException:
    message = str(error)
    if "not found" in message:
        code = status.HTTP_404_NOT_FOUND
    elif "do not exist" in message:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=message)
