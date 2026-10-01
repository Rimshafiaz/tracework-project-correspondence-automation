import os
from base64 import urlsafe_b64encode
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.adapters.gmail.message_parser import parse_gmail_message
from app.adapters.gmail.normalizer import normalize_gmail_message
from app.models.attachment import Attachment
from app.models.correspondence_event import CorrespondenceEvent
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.services.correspondence_ingestion import CorrespondenceIngestionService

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
def test_gmail_payload_reaches_postgres_once_with_attachment_metadata() -> None:
    engine = create_engine(DATABASE_URL)
    external_event_id = f"acceptance-{uuid4()}"
    body = urlsafe_b64encode(b"Latest update").decode().rstrip("=")
    payload = {
        "id": external_event_id,
        "threadId": "acceptance-thread",
        "internalDate": "1790838000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "Subject", "value": "Acceptance check"},
            ],
            "body": {},
            "parts": [
                {"mimeType": "text/plain", "body": {"data": body}},
                {
                    "partId": "1",
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "body": {"attachmentId": "attachment-1", "size": 321},
                },
            ],
        },
    }

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, expire_on_commit=False) as session:
                service = CorrespondenceIngestionService(
                    CorrespondenceEventRepository(session),
                    AttachmentRepository(session),
                )
                correspondence = normalize_gmail_message(parse_gmail_message(payload))

                first = service.ingest(correspondence)
                repeated = service.ingest(correspondence)

                assert first.created is True
                assert repeated.created is False
                assert repeated.event.id == first.event.id
                assert session.scalar(
                    select(func.count())
                    .select_from(CorrespondenceEvent)
                    .where(
                        CorrespondenceEvent.source == "gmail",
                        CorrespondenceEvent.external_event_id == external_event_id,
                    )
                ) == 1
                assert session.scalar(
                    select(func.count())
                    .select_from(Attachment)
                    .where(Attachment.correspondence_event_id == first.event.id)
                ) == 1
        finally:
            transaction.rollback()
            engine.dispose()
