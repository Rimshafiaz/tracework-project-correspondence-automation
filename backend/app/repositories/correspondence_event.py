from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import CorrespondenceProcessingState


class CorrespondenceEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        source: str,
        external_event_id: str,
        sender_identifier: str,
        body: str,
        received_at: datetime,
        external_conversation_id: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        subject: str | None = None,
        source_metadata: dict[str, object] | None = None,
    ) -> CorrespondenceEvent:
        event = CorrespondenceEvent(
            source=source,
            external_event_id=external_event_id,
            external_conversation_id=external_conversation_id,
            sender_identifier=sender_identifier,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body=body,
            received_at=received_at,
            processing_state=CorrespondenceProcessingState.PENDING,
            source_metadata=source_metadata,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get(self, event_id: UUID) -> CorrespondenceEvent | None:
        return self.session.get(CorrespondenceEvent, event_id)

    def get_by_external_identity(
        self, *, source: str, external_event_id: str
    ) -> CorrespondenceEvent | None:
        statement = select(CorrespondenceEvent).where(
            CorrespondenceEvent.source == source,
            CorrespondenceEvent.external_event_id == external_event_id,
        )
        return self.session.scalar(statement)

    def list_for_conversation(
        self, *, source: str, external_conversation_id: str
    ) -> Sequence[CorrespondenceEvent]:
        statement = (
            select(CorrespondenceEvent)
            .where(
                CorrespondenceEvent.source == source,
                CorrespondenceEvent.external_conversation_id
                == external_conversation_id,
            )
            .order_by(CorrespondenceEvent.received_at, CorrespondenceEvent.id)
        )
        return self.session.scalars(statement).all()

    def update_processing_state(
        self,
        event: CorrespondenceEvent,
        *,
        state: CorrespondenceProcessingState,
        failure_metadata: dict[str, object] | None = None,
    ) -> CorrespondenceEvent:
        event.processing_state = state
        event.failure_metadata = failure_metadata
        self.session.flush()
        return event
