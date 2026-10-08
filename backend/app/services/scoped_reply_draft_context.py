from uuid import UUID

from app.contracts.follow_up import DueFollowUpContext
from app.contracts.reply_draft_context import (
    FollowUpReplyScope,
    ReplyDraftEligibility,
    ReplyDraftEligibilityStatus,
    ReplyDraftReadLimits,
    ScopedReplyCorrespondence,
    ScopedReplyDocumentRevisionStatus,
    ScopedReplyDocumentRevisionStatuses,
    ScopedReplyEvidence,
    ScopedReplyFollowUpHistory,
    ScopedReplyFollowUpHistoryItem,
    ScopedReplyProjectSummary,
    ScopedReplyRecentCorrespondence,
    ScopedReplyRequirementContext,
)
from app.models.enums import EvidenceValidity
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.document import DocumentRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.requirement import RequirementRepository
from app.services.follow_up_read import FollowUpReadService
from app.services.reply_draft_eligibility import ReplyDraftEligibilityService


class ScopedReplyDraftContextError(RuntimeError):
    pass


class ScopedReplyDraftContextNotDraftableError(ScopedReplyDraftContextError):
    def __init__(self, eligibility: ReplyDraftEligibility) -> None:
        super().__init__("follow-up is not draftable in S2 V1")
        self.eligibility = eligibility


class ScopedReplyDraftContextIntegrityError(ScopedReplyDraftContextError):
    pass


class ScopedReplyDraftContextService:
    """Creates a read-only reply context from a freshly derived FollowUp scope."""

    def __init__(
        self,
        *,
        eligibility_service: ReplyDraftEligibilityService,
        follow_up_read_service: FollowUpReadService,
        project_repository: ProjectRepository,
        requirement_repository: RequirementRepository,
        correspondence_repository: CorrespondenceEventRepository,
        follow_up_repository: FollowUpRepository,
        document_repository: DocumentRepository,
        lineage_repository: LineageRepository,
    ) -> None:
        self.eligibility_service = eligibility_service
        self.follow_up_read_service = follow_up_read_service
        self.projects = project_repository
        self.requirements = requirement_repository
        self.correspondence = correspondence_repository
        self.follow_ups = follow_up_repository
        self.documents = document_repository
        self.lineage = lineage_repository
        self._limits = ReplyDraftReadLimits()

    def open(self, follow_up_id: UUID) -> "_ScopedReplyDraftContext":
        eligibility = self.eligibility_service.assess(follow_up_id)
        if (
            eligibility.status is not ReplyDraftEligibilityStatus.DRAFTABLE
            or eligibility.scope is None
        ):
            raise ScopedReplyDraftContextNotDraftableError(eligibility)
        return _ScopedReplyDraftContext(
            scope=eligibility.scope,
            follow_up_read_service=self.follow_up_read_service,
            project_repository=self.projects,
            requirement_repository=self.requirements,
            correspondence_repository=self.correspondence,
            follow_up_repository=self.follow_ups,
            document_repository=self.documents,
            lineage_repository=self.lineage,
            limits=self._limits,
        )


class _ScopedReplyDraftContext:
    """No-argument reads constrained by an internally derived FollowUp scope."""

    def __init__(
        self,
        *,
        scope: FollowUpReplyScope,
        follow_up_read_service: FollowUpReadService,
        project_repository: ProjectRepository,
        requirement_repository: RequirementRepository,
        correspondence_repository: CorrespondenceEventRepository,
        follow_up_repository: FollowUpRepository,
        document_repository: DocumentRepository,
        lineage_repository: LineageRepository,
        limits: ReplyDraftReadLimits,
    ) -> None:
        self._scope = scope
        self._follow_up_read_service = follow_up_read_service
        self._projects = project_repository
        self._requirements = requirement_repository
        self._correspondence = correspondence_repository
        self._follow_ups = follow_up_repository
        self._documents = document_repository
        self._lineage = lineage_repository
        self._limits = limits

    def get_due_follow_up(self) -> DueFollowUpContext:
        context = self._follow_up_read_service.get_follow_up(self._scope.follow_up_id)
        if (
            context.project_id != self._scope.project_id
            or context.requirement_id != self._scope.requirement_id
        ):
            raise ScopedReplyDraftContextIntegrityError(
                "persisted due follow-up no longer matches the derived scope"
            )
        return context

    def get_project_summary(self) -> ScopedReplyProjectSummary:
        project = self._projects.get(self._scope.project_id)
        if project is None or project.id != self._scope.project_id:
            raise ScopedReplyDraftContextIntegrityError("scoped project was not found")
        return ScopedReplyProjectSummary(
            project_id=project.id,
            project_code=project.project_code,
            name=project.name,
            status=project.status,
        )

    def get_requirement_context(self) -> ScopedReplyRequirementContext:
        requirement = self._requirements.get(self._scope.requirement_id)
        if requirement is None or requirement.project_id != self._scope.project_id:
            raise ScopedReplyDraftContextIntegrityError(
                "scoped requirement does not belong to the scoped project"
            )
        rows = tuple(
            self._lineage.list_valid_evidence_for_requirements(
                project_id=self._scope.project_id,
                requirement_ids={self._scope.requirement_id},
                limit=self._limits.max_evidence_items + 1,
            )
        )
        evidence = rows[: self._limits.max_evidence_items]
        if any(
            item.project_id != self._scope.project_id
            or item.requirement_id != self._scope.requirement_id
            or item.validity is not EvidenceValidity.VALID
            for item in evidence
        ):
            raise ScopedReplyDraftContextIntegrityError(
                "evidence does not match the scoped requirement"
            )
        return ScopedReplyRequirementContext(
            requirement_id=requirement.id,
            project_id=requirement.project_id,
            name=requirement.name,
            description=requirement.description,
            state=requirement.state,
            expected_date=requirement.expected_date,
            evidence=tuple(self._evidence(item) for item in evidence),
            evidence_limit_reached=len(rows) > self._limits.max_evidence_items,
        )

    def list_recent_correspondence(self) -> ScopedReplyRecentCorrespondence:
        rows = tuple(
            self._correspondence.list_authoritatively_linked_for_project(
                project_id=self._scope.project_id,
                limit=self._limits.max_recent_correspondence + 1,
            )
        )
        records = rows[: self._limits.max_recent_correspondence]
        return ScopedReplyRecentCorrespondence(
            correspondence=tuple(self._correspondence_record(item) for item in records),
            limit_reached=len(rows) > self._limits.max_recent_correspondence,
        )

    def list_follow_up_history(self) -> ScopedReplyFollowUpHistory:
        rows = tuple(
            self._follow_ups.list_history(
                requirement_id=self._scope.requirement_id,
                purpose=self.get_due_follow_up().purpose,
                limit=self._limits.max_follow_up_history + 1,
            )
        )
        records = rows[: self._limits.max_follow_up_history]
        if any(
            item.project_id != self._scope.project_id
            or item.requirement_id != self._scope.requirement_id
            for item in records
        ):
            raise ScopedReplyDraftContextIntegrityError(
                "follow-up history does not match the derived scope"
            )
        return ScopedReplyFollowUpHistory(
            follow_ups=tuple(self._history_item(item) for item in records),
            limit_reached=len(rows) > self._limits.max_follow_up_history,
        )

    def list_document_revision_status(self) -> ScopedReplyDocumentRevisionStatuses:
        rows = tuple(
            self._documents.list_revision_status_for_project(
                project_id=self._scope.project_id,
                limit=self._limits.max_document_statuses + 1,
            )
        )
        records = rows[: self._limits.max_document_statuses]
        if any(item.project_id != self._scope.project_id for item in records):
            raise ScopedReplyDraftContextIntegrityError(
                "document status does not match the scoped project"
            )
        return ScopedReplyDocumentRevisionStatuses(
            documents=tuple(self._document_status(item) for item in records),
            limit_reached=len(rows) > self._limits.max_document_statuses,
        )

    def _evidence(self, item) -> ScopedReplyEvidence:
        excerpt, truncated = self._exact_prefix(
            item.excerpt, self._limits.max_evidence_excerpt_characters
        )
        return ScopedReplyEvidence(
            evidence_item_id=item.id,
            correspondence_event_id=item.correspondence_event_id,
            attachment_id=item.attachment_id,
            source_type=item.source_type,
            excerpt=excerpt,
            excerpt_truncated=truncated,
            page_number=item.page_number,
            section=item.section,
            validity=item.validity,
        )

    def _correspondence_record(self, item) -> ScopedReplyCorrespondence:
        body, truncated = self._exact_prefix(
            item.body, self._limits.max_correspondence_body_characters
        )
        return ScopedReplyCorrespondence(
            correspondence_event_id=item.id,
            source=item.source,
            external_message_id=item.external_event_id,
            external_conversation_id=item.external_conversation_id,
            sender_identifier=item.sender_identifier,
            sender_email=item.sender_email,
            sender_name=item.sender_name,
            received_at=item.received_at,
            subject=item.subject,
            body=body,
            body_truncated=truncated,
        )

    @staticmethod
    def _history_item(item) -> ScopedReplyFollowUpHistoryItem:
        return ScopedReplyFollowUpHistoryItem(
            follow_up_id=item.id,
            purpose=item.purpose,
            reason=item.reason,
            expected_date=item.expected_date,
            due_on=item.due_on,
            status=item.status,
            became_due_at=item.became_due_at,
            cancelled_at=item.cancelled_at,
            cancel_reason=item.cancel_reason,
            completed_at=item.completed_at,
        )

    @staticmethod
    def _document_status(item) -> ScopedReplyDocumentRevisionStatus:
        return ScopedReplyDocumentRevisionStatus(
            document_id=item.id,
            source_attachment_id=item.source_attachment_id,
            filename=item.filename,
            category=item.category,
            filing_status=item.filing_status,
            document_family_key=item.document_family_key,
            revision_label=item.revision_label,
            revision_normalized=item.revision_normalized,
            revision_order=item.revision_order,
            revision_status=item.revision_status,
            revision_decided_at=item.revision_decided_at,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    def _exact_prefix(value: str, limit: int) -> tuple[str, bool]:
        return value[:limit], len(value) > limit
