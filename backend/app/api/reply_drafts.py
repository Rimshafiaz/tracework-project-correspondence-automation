from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.gmail.client import create_gmail_client
from app.api.dependencies import get_session
from app.contracts.reply_draft import ReplyDraftContent, ReplyDraftSnapshot
from app.contracts.reply_draft_send import ReplyDraftSendResult, ReplyDraftSendStatus
from app.core.auth import AuthenticatedOperator, require_authenticated_operator
from app.core.config import Settings, get_settings
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.repositories.requirement import RequirementRepository
from app.services.reply_draft_eligibility import ReplyDraftEligibilityService
from app.services.reply_draft_lifecycle import ReplyDraftLifecycleError, ReplyDraftLifecycleService
from app.services.reply_draft_review import ReplyDraftReviewService
from app.services.reply_draft_send import (
    ReplyDraftSendAuthorizationError,
    ReplyDraftSendConfigurationError,
    ReplyDraftSendError,
    ReplyDraftSendService,
    ReplyDraftSendStateError,
)

router = APIRouter(
    tags=["reply-drafts"],
    dependencies=[Depends(require_authenticated_operator)],
)


def _lifecycle(session: Session) -> ReplyDraftLifecycleService:
    return ReplyDraftLifecycleService(
        session=session,
        follow_up_repository=FollowUpRepository(session),
        requirement_repository=RequirementRepository(session),
        reply_draft_repository=ReplyDraftRepository(session),
    )


def get_reply_draft_review_service(
    session: Session = Depends(get_session),
) -> ReplyDraftReviewService:
    return ReplyDraftReviewService(
        session=session,
        reply_draft_repository=ReplyDraftRepository(session),
        lifecycle_service=_lifecycle(session),
        lineage_repository=LineageRepository(session),
    )


def get_reply_draft_send_service(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReplyDraftSendService:
    follow_ups = FollowUpRepository(session)
    requirements = RequirementRepository(session)
    correspondence = CorrespondenceEventRepository(session)
    links = CorrespondenceProjectLinkRepository(session)
    contacts = ProjectContactRepository(session)
    lineage = LineageRepository(session)
    return ReplyDraftSendService(
        session=session,
        settings=settings,
        gmail_service=create_gmail_client(settings),
        eligibility_service=ReplyDraftEligibilityService(
            follow_up_repository=follow_ups,
            requirement_repository=requirements,
            lineage_repository=lineage,
            correspondence_repository=correspondence,
            project_link_repository=links,
            contact_repository=contacts,
        ),
        reply_draft_lifecycle=_lifecycle(session),
        reply_draft_repository=ReplyDraftRepository(session),
        follow_up_repository=follow_ups,
        requirement_repository=requirements,
        correspondence_repository=correspondence,
        contact_repository=contacts,
        lineage_repository=lineage,
    )


@router.get("/reply-drafts/{reply_draft_id}", response_model=ReplyDraftSnapshot)
def get_reply_draft(
    reply_draft_id: UUID,
    service: ReplyDraftReviewService = Depends(get_reply_draft_review_service),
) -> ReplyDraftSnapshot:
    try:
        return service.get(reply_draft_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reply draft was not found") from exc


@router.get("/projects/{project_id}/reply-drafts", response_model=list[ReplyDraftSnapshot])
def list_project_reply_drafts(
    project_id: UUID,
    service: ReplyDraftReviewService = Depends(get_reply_draft_review_service),
) -> tuple[ReplyDraftSnapshot, ...]:
    return service.list_for_project(project_id)


@router.patch("/reply-drafts/{reply_draft_id}", response_model=ReplyDraftSnapshot)
def edit_reply_draft(
    reply_draft_id: UUID,
    content: ReplyDraftContent,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ReplyDraftReviewService = Depends(get_reply_draft_review_service),
) -> ReplyDraftSnapshot:
    try:
        result = service.edit(reply_draft_id, content=content, operator_subject=operator.subject)
        service.session.commit()
        return result
    except LookupError as exc:
        service.session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reply draft was not found") from exc
    except ReplyDraftLifecycleError as exc:
        service.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/reply-drafts/{reply_draft_id}/approve", response_model=ReplyDraftSnapshot)
def approve_reply_draft(
    reply_draft_id: UUID,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ReplyDraftReviewService = Depends(get_reply_draft_review_service),
) -> ReplyDraftSnapshot:
    try:
        result = service.approve(reply_draft_id, operator_subject=operator.subject)
        service.session.commit()
        return result
    except (LookupError, ReplyDraftLifecycleError) as exc:
        service.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/reply-drafts/{reply_draft_id}/reject", response_model=ReplyDraftSnapshot)
def reject_reply_draft(
    reply_draft_id: UUID,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ReplyDraftReviewService = Depends(get_reply_draft_review_service),
) -> ReplyDraftSnapshot:
    try:
        result = service.reject(reply_draft_id, operator_subject=operator.subject)
        service.session.commit()
        return result
    except (LookupError, ReplyDraftLifecycleError) as exc:
        service.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/reply-drafts/{reply_draft_id}/send", response_model=ReplyDraftSendResult)
def send_reply_draft(
    reply_draft_id: UUID,
    operator: AuthenticatedOperator = Depends(require_authenticated_operator),
    service: ReplyDraftSendService = Depends(get_reply_draft_send_service),
) -> ReplyDraftSendResult:
    try:
        result = service.send(reply_draft_id, operator_subject=operator.subject)
    except ReplyDraftSendConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (ReplyDraftSendAuthorizationError, ReplyDraftSendStateError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReplyDraftSendError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="reply send could not be completed") from exc
    if result.status in {
        ReplyDraftSendStatus.SEND_STILL_PENDING,
        ReplyDraftSendStatus.RETRYABLE_FAILURE,
        ReplyDraftSendStatus.AMBIGUOUS_RECOVERY,
        ReplyDraftSendStatus.ACTION_REQUIRED,
    }:
        return result
    return result
