from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ProjectStatus, RequirementState


class ProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_code: str
    name: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ProjectWorkspaceIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    identifier_type: str
    display_value: str
    verified: bool


class ProjectWorkspaceRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    name: str
    description: str | None
    state: RequirementState
    expected_date: date | None
    created_at: datetime
    updated_at: datetime


class ProjectWorkspaceContact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    email: str
    display_name: str
    role: str | None
    is_active: bool


class ProjectWorkspace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project: ProjectSummary
    identifiers: tuple[ProjectWorkspaceIdentifier, ...]
    requirements: tuple[ProjectWorkspaceRequirement, ...]
    contacts: tuple[ProjectWorkspaceContact, ...] = ()
