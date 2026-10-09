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
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.follow_up import FollowUpRepository
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
from app.services.follow_up_lifecycle import FollowUpLifecycleService
from app.services.policy.requirement_context import RequirementPolicyContextService
from app.services.requirement_review_decision import (
    RequirementReviewDecisionError,
    RequirementReviewDecisionCode,
    RequirementReviewDecisionService,
)
from app.contracts.requirement_review_decision import (
    RequirementReviewDecisionResponse,
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


def get_requirement_review_decision_service(
    session: Session = Depends(get_session),
) -> RequirementReviewDecisionService:
    requirements = RequirementRepository(session)
    lineage = LineageRepository(session)
    follow_ups = FollowUpRepository(session)
    return RequirementReviewDecisionService(
        session=session,
        review_repository=ReviewItemRepository(session),
        lineage_repository=lineage,
        requirement_repository=requirements,
        context_service=RequirementPolicyContextService(
            correspondence_repository=CorrespondenceEventRepository(session),
            project_link_repository=CorrespondenceProjectLinkRepository(session),
            requirement_repository=requirements,
            attachment_repository=AttachmentRepository(session),
            lineage_repository=lineage,
        ),
        follow_up_lifecycle_service=FollowUpLifecycleService(
            session=session,
            requirement_repository=requirements,
            follow_up_repository=follow_ups,
            audit_repository=lineage,
        ),
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


@router.post("/{review_item_id}/approve", response_model=RequirementReviewDecisionResponse)
def approve_requirement_review(
    review_item_id: UUID,
    operator=Depends(require_authenticated_operator),
    service: RequirementReviewDecisionService = Depends(
        get_requirement_review_decision_service
    ),
) -> RequirementReviewDecisionResponse:
    try:
        result = service.approve(review_item_id, operator_subject=operator.subject)
        return _requirement_decision_response(result)
    except RequirementReviewDecisionError as exc:
        raise _requirement_decision_http_error(exc) from exc


@router.post("/{review_item_id}/reject", response_model=RequirementReviewDecisionResponse)
def reject_requirement_review(
    review_item_id: UUID,
    operator=Depends(require_authenticated_operator),
    service: RequirementReviewDecisionService = Depends(
        get_requirement_review_decision_service
    ),
) -> RequirementReviewDecisionResponse:
    try:
        result = service.reject(review_item_id, operator_subject=operator.subject)
        return _requirement_decision_response(result)
    except RequirementReviewDecisionError as exc:
        raise _requirement_decision_http_error(exc) from exc


def _requirement_decision_response(result) -> RequirementReviewDecisionResponse:
    return RequirementReviewDecisionResponse(
        review_item_id=result.review_item.id,
        status=result.review_item.status,
        action=result.action,
        applied_requirement_ids=result.applied_requirement_ids,
        follow_up_ids=result.follow_up_ids,
        idempotent_replay=result.idempotent_replay,
    )


def _requirement_decision_http_error(error: RequirementReviewDecisionError) -> HTTPException:
    if error.code is RequirementReviewDecisionCode.REMAINING_SUPPORTING_EVIDENCE:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": error.code.value,
            "message": "This retraction cannot be applied because other valid evidence still supports the requirement.",
        })
    code = status.HTTP_404_NOT_FOUND if "not found" in str(error) else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=str(error))
