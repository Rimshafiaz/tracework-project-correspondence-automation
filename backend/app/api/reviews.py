from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.contracts.review_queue import ReviewQueueSummary, ReviewReadDetail
from app.core.auth import require_authenticated_operator
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.attachment import AttachmentRepository
from app.repositories.document import DocumentRepository
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository
from app.repositories.project import ProjectRepository
from app.services.policy.requirement_review_handoff import (
    RequirementReviewHandoffService,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryService,
)
from app.services.review_queue import (
    ReviewQueueIntegrityError,
    ReviewQueueNotFoundError,
    ReviewQueueQueryService,
)

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    dependencies=[Depends(require_authenticated_operator)],
)


def get_review_queue_query_service(
    session: Session = Depends(get_session),
) -> ReviewQueueQueryService:
    review_repository = ReviewItemRepository(session)
    correspondence_repository = CorrespondenceEventRepository(session)
    lineage_repository = LineageRepository(session)
    return ReviewQueueQueryService(
        review_repository=review_repository,
        correspondence_repository=correspondence_repository,
        project_resolution_query_service=ProjectResolutionReviewQueryService(
            review_repository=review_repository,
            correspondence_repository=correspondence_repository,
            lineage_repository=lineage_repository,
        ),
        requirement_handoff_service=RequirementReviewHandoffService(
            lineage_repository=lineage_repository,
            requirement_repository=RequirementRepository(session),
        ),
        attachment_repository=AttachmentRepository(session),
        document_repository=DocumentRepository(session),
        project_repository=ProjectRepository(session),
    )


@router.get("", response_model=list[ReviewQueueSummary])
def list_pending_reviews(
    service: ReviewQueueQueryService = Depends(get_review_queue_query_service),
) -> tuple[ReviewQueueSummary, ...]:
    return service.list_pending()


@router.get("/{review_item_id}", response_model=ReviewReadDetail)
def get_review_detail(
    review_item_id: UUID,
    service: ReviewQueueQueryService = Depends(get_review_queue_query_service),
) -> ReviewReadDetail:
    try:
        return service.get_detail(review_item_id)
    except ReviewQueueNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review item was not found",
        ) from exc
    except ReviewQueueIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="review history is inconsistent",
        ) from exc
