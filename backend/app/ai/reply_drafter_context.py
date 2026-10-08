from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.contracts.follow_up import DueFollowUpContext
from app.contracts.reply_draft_context import (
    ScopedReplyDocumentRevisionStatuses,
    ScopedReplyFollowUpHistory,
    ScopedReplyProjectSummary,
    ScopedReplyRecentCorrespondence,
    ScopedReplyRequirementContext,
)
from app.ai.reply_drafter_schemas import ReplyDraftGroundingReference


class ReplyDrafterToolName(StrEnum):
    GET_DUE_FOLLOW_UP = "get_due_follow_up"
    GET_PROJECT_SUMMARY = "get_project_summary"
    GET_REQUIREMENT_CONTEXT = "get_requirement_context"
    LIST_RECENT_CORRESPONDENCE = "list_recent_correspondence"
    LIST_FOLLOW_UP_HISTORY = "list_follow_up_history"
    LIST_DOCUMENT_REVISION_STATUS = "list_document_revision_status"


class ReplyDrafterToolTraceEntry(BaseModel):
    """Bounded typed context shown by one approved tool; never hidden reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: ReplyDrafterToolName
    result: dict[str, object]
    exposed_references: tuple[ReplyDraftGroundingReference, ...]


class ReplyDrafterRunTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    follow_up_id: UUID
    entries: tuple[ReplyDrafterToolTraceEntry, ...]


class ScopedReplyDrafterContext(Protocol):
    def get_due_follow_up(self) -> DueFollowUpContext: ...

    def get_project_summary(self) -> ScopedReplyProjectSummary: ...

    def get_requirement_context(self) -> ScopedReplyRequirementContext: ...

    def list_recent_correspondence(self) -> ScopedReplyRecentCorrespondence: ...

    def list_follow_up_history(self) -> ScopedReplyFollowUpHistory: ...

    def list_document_revision_status(self) -> ScopedReplyDocumentRevisionStatuses: ...


@dataclass
class ReplyDrafterRunTraceAccumulator:
    follow_up_id: UUID
    entries: list[ReplyDrafterToolTraceEntry] = field(default_factory=list)

    def snapshot(self) -> ReplyDrafterRunTrace:
        return ReplyDrafterRunTrace(
            follow_up_id=self.follow_up_id,
            entries=tuple(self.entries),
        )

    def record(
        self,
        *,
        tool_name: ReplyDrafterToolName,
        result: dict[str, object],
        exposed_references: tuple[ReplyDraftGroundingReference, ...],
    ) -> None:
        self.entries.append(
            ReplyDrafterToolTraceEntry(
                tool_name=tool_name,
                result=result,
                exposed_references=exposed_references,
            )
        )


@dataclass(frozen=True)
class ReplyDrafterDeps:
    """Application-owned dependencies for later scoped tool binding."""

    scoped_context: ScopedReplyDrafterContext
    trace: ReplyDrafterRunTraceAccumulator
