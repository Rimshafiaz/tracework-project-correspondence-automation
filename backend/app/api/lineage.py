from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.contracts.evidence_lineage import EvidenceLineage
from app.core.auth import require_authenticated_operator
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import (
    CorrespondenceProjectLinkRepository,
)
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.evidence_lineage import EvidenceLineageError, EvidenceLineageService

router = APIRouter(
    prefix="/transitions",
    tags=["lineage"],
    dependencies=[Depends(require_authenticated_operator)],
)


def get_evidence_lineage_service(
    session: Session = Depends(get_session),
) -> EvidenceLineageService:
    return EvidenceLineageService(
        lineage_repository=LineageRepository(session),
        correspondence_repository=CorrespondenceEventRepository(session),
        attachment_repository=AttachmentRepository(session),
        project_link_repository=CorrespondenceProjectLinkRepository(session),
        requirement_repository=RequirementRepository(session),
        review_repository=ReviewItemRepository(session),
    )


@router.get("/{transition_id}/lineage", response_model=EvidenceLineage)
def get_evidence_lineage(
    transition_id: UUID,
    service: EvidenceLineageService = Depends(get_evidence_lineage_service),
) -> EvidenceLineage:
    try:
        return service.load(transition_id)
    except EvidenceLineageError as exc:
        if str(exc) == "state transition was not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="state transition was not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="evidence lineage is inconsistent",
        ) from exc
