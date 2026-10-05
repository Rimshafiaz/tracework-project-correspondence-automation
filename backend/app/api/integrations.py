from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.contracts.gmail_status import GmailStatus
from app.core.auth import require_authenticated_operator
from app.core.config import get_settings
from app.repositories.ingestion_cursor import IngestionCursorRepository
from app.services.gmail_status import GmailStatusService

router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_authenticated_operator)],
)


def get_gmail_status_service(
    session: Session = Depends(get_session),
) -> GmailStatusService:
    return GmailStatusService(
        settings=get_settings(),
        cursor_repository=IngestionCursorRepository(session),
    )


@router.get("/gmail/status", response_model=GmailStatus)
def get_gmail_status(
    service: GmailStatusService = Depends(get_gmail_status_service),
) -> GmailStatus:
    return service.load()
