from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.correspondence_event import CorrespondenceEvent
from app.models.correspondence_project_link import CorrespondenceProjectLink


class CorrespondenceProjectLinkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_approved_link(
        self, *, correspondence_event_id: UUID, project_id: UUID
    ) -> CorrespondenceProjectLink:
        link = CorrespondenceProjectLink(
            correspondence_event_id=correspondence_event_id,
            project_id=project_id,
        )
        self.session.add(link)
        self.session.flush()
        return link

    def list_approved_project_ids_for_conversation(
        self, *, source: str, external_conversation_id: str
    ) -> Sequence[UUID]:
        if not source.strip() or not external_conversation_id.strip():
            return []
        statement = (
            select(CorrespondenceProjectLink.project_id)
            .join(CorrespondenceEvent)
            .where(
                CorrespondenceEvent.source == source,
                CorrespondenceEvent.external_conversation_id
                == external_conversation_id,
            )
            .distinct()
            .order_by(CorrespondenceProjectLink.project_id)
        )
        return self.session.scalars(statement).all()

    def get_unique_approved_project_id_for_conversation(
        self, *, source: str, external_conversation_id: str
    ) -> UUID | None:
        project_ids = self.list_approved_project_ids_for_conversation(
            source=source,
            external_conversation_id=external_conversation_id,
        )
        return project_ids[0] if len(project_ids) == 1 else None
