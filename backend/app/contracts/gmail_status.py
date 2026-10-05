from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.models.enums import IngestionCursorStatus


class GmailIntegrationStatus(StrEnum):
    DISABLED = "DISABLED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    CONFIGURED = "CONFIGURED"
    ACTIVE = "ACTIVE"
    RESYNC_REQUIRED = "RESYNC_REQUIRED"


class GmailStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: GmailIntegrationStatus
    configured_account_email: str | None = None
    stored_authorization_present: bool
    cursor_status: IngestionCursorStatus | None = None
    last_attempted_at: datetime | None = None
    last_succeeded_at: datetime | None = None
