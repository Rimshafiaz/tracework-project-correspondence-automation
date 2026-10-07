import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.drive.client import DriveProviderError, GoogleDriveClient, sanitize_drive_name
from app.ai.schemas import ProjectResolution
from app.contracts.document_filing import (
    DOCUMENT_FILING_ENTITY_TYPE,
    CorrespondenceDocumentFilingResult,
    DocumentFilingAuthorization,
    DocumentFilingEffect,
    DocumentFilingOutcome,
    DocumentFilingOutcomeStatus,
    DocumentFilingSkipReason,
)
from app.models.attachment import Attachment
from app.models.correspondence_event import CorrespondenceEvent
from app.models.enums import DocumentFilingStatus, PolicyDecision, ReviewStatus, TransitionDisposition, TransitionStatus
from app.models.policy_evaluation import PolicyEvaluation
from app.models.project import Project
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.document import DocumentRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.review_item import ReviewItemRepository

DOCUMENT_FILED_AUDIT_EVENT = "document_filed"
DOCUMENT_FILING_FAILURE_CODE = "DRIVE_PROVIDER_UNAVAILABLE"

AttachmentContentLoader = Callable[[CorrespondenceEvent, Attachment], bytes]


class DocumentFilingIntegrityError(RuntimeError):
    pass


class AttachmentContentUnavailable(RuntimeError):
    pass


class DocumentFilingService:
    """Files attachments only after durable project authorization exists."""

    def __init__(
        self,
        *,
        session: Session,
        drive_client: GoogleDriveClient,
        root_folder_name: str,
        default_category: str,
        content_loader: AttachmentContentLoader,
        attachment_repository: AttachmentRepository,
        document_repository: DocumentRepository,
        project_repository: ProjectRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
        review_repository: ReviewItemRepository,
        lineage_repository: LineageRepository,
    ) -> None:
        self.session = session
        self.drive_client = drive_client
        self.root_folder_name = sanitize_drive_name(root_folder_name)
        self.default_category = sanitize_drive_name(default_category)
        self.content_loader = content_loader
        self.attachment_repository = attachment_repository
        self.document_repository = document_repository
        self.project_repository = project_repository
        self.project_link_repository = project_link_repository
        self.review_repository = review_repository
        self.lineage_repository = lineage_repository

    def file_for_project_resolution(
        self,
        *,
        proposal_id: UUID,
        policy_evaluation_id: UUID,
    ) -> CorrespondenceDocumentFilingResult:
        proposal = self.lineage_repository.get_proposal(proposal_id)
        evaluation = self.lineage_repository.get_policy_evaluation_by_id(
            policy_evaluation_id
        )
        if proposal is None or evaluation is None or evaluation.ai_proposal_id != proposal.id:
            raise DocumentFilingIntegrityError("project-resolution lineage is incomplete")
        try:
            resolution = ProjectResolution.model_validate(proposal.structured_output)
        except ValidationError as exc:
            raise DocumentFilingIntegrityError(
                "persisted project resolution is invalid"
            ) from exc

        attachments = tuple(
            self.attachment_repository.list_for_correspondence_event(
                proposal.correspondence_event_id
            )
        )
        if not attachments:
            return CorrespondenceDocumentFilingResult(
                correspondence_event_id=proposal.correspondence_event_id
            )

        project_ids = tuple(
            self.project_link_repository.list_approved_project_ids_for_event(
                proposal.correspondence_event_id
            )
        )
        authorization, blocked = self._authorization(
            proposal.correspondence_event_id,
            evaluation,
            bool(project_ids),
        )
        if blocked is not None:
            return self._all_skipped(proposal.correspondence_event_id, attachments, blocked)

        event = proposal.correspondence_event
        outcomes = []
        for attachment in attachments:
            project_id, reason = self._attachment_project(
                attachment_id=attachment.id,
                authoritative_project_ids=project_ids,
                resolution=resolution,
            )
            if project_id is None:
                outcomes.append(
                    DocumentFilingOutcome(
                        attachment_id=attachment.id,
                        status=DocumentFilingOutcomeStatus.SKIPPED,
                        skip_reason=reason,
                    )
                )
                continue
            outcomes.append(
                self._file_one(
                    event=event,
                    attachment=attachment,
                    project_id=project_id,
                    proposal_id=proposal.id,
                    evaluation=evaluation,
                    authorization=authorization,
                )
            )
        return CorrespondenceDocumentFilingResult(
            correspondence_event_id=proposal.correspondence_event_id,
            outcomes=tuple(outcomes),
        )

    def _authorization(
        self,
        correspondence_event_id: UUID,
        evaluation: PolicyEvaluation,
        has_links: bool,
    ) -> tuple[DocumentFilingAuthorization, DocumentFilingSkipReason | None]:
        if evaluation.decision is PolicyDecision.ALLOW_AUTO_ACTION:
            if not has_links:
                return (
                    DocumentFilingAuthorization.AUTOMATIC_PROJECT_POLICY,
                    DocumentFilingSkipReason.PROJECT_NOT_AUTHORIZED,
                )
            return DocumentFilingAuthorization.AUTOMATIC_PROJECT_POLICY, None
        if evaluation.decision is PolicyDecision.REJECT_PROPOSAL:
            return (
                DocumentFilingAuthorization.AUTOMATIC_PROJECT_POLICY,
                DocumentFilingSkipReason.PROJECT_NOT_AUTHORIZED,
            )
        transition = self.review_repository.get_project_resolution_transition(
            policy_evaluation_id=evaluation.id,
            correspondence_event_id=correspondence_event_id,
        )
        review = (
            self.review_repository.get_by_state_transition(transition.id)
            if transition is not None
            else None
        )
        if review is None or review.status is ReviewStatus.PENDING:
            return (
                DocumentFilingAuthorization.HUMAN_PROJECT_REVIEW,
                DocumentFilingSkipReason.PROJECT_REVIEW_PENDING,
            )
        if review.status is ReviewStatus.REJECTED or not has_links:
            return (
                DocumentFilingAuthorization.HUMAN_PROJECT_REVIEW,
                DocumentFilingSkipReason.PROJECT_REVIEW_REJECTED,
            )
        return DocumentFilingAuthorization.HUMAN_PROJECT_REVIEW, None

    @staticmethod
    def _attachment_project(
        *,
        attachment_id: UUID,
        authoritative_project_ids: Sequence[UUID],
        resolution: ProjectResolution,
    ) -> tuple[UUID | None, DocumentFilingSkipReason | None]:
        conflicts = tuple(
            item
            for item in resolution.conflicts
            if any(ref.attachment_id == attachment_id for ref in item.signal_references)
            or any(src.attachment_id == attachment_id for src in item.source_evidence)
        )
        if conflicts:
            return None, DocumentFilingSkipReason.ATTACHMENT_PROJECT_CONFLICT

        supported = {
            item.project_id
            for item in resolution.evidence
            if (
                any(ref.attachment_id == attachment_id for ref in item.signal_references)
                or any(src.attachment_id == attachment_id for src in item.source_evidence)
            )
        }
        if supported - set(authoritative_project_ids):
            return None, DocumentFilingSkipReason.ATTACHMENT_PROJECT_CONFLICT
        if len(authoritative_project_ids) == 1:
            return authoritative_project_ids[0], None
        if len(supported) != 1:
            return None, DocumentFilingSkipReason.MULTI_PROJECT_ATTACHMENT_AMBIGUOUS
        project_id = next(iter(supported))
        return project_id, None

    def _file_one(
        self,
        *,
        event: CorrespondenceEvent,
        attachment: Attachment,
        project_id: UUID,
        proposal_id: UUID,
        evaluation: PolicyEvaluation,
        authorization: DocumentFilingAuthorization,
    ) -> DocumentFilingOutcome:
        existing = self.document_repository.get_by_project_attachment(
            project_id=project_id,
            source_attachment_id=attachment.id,
        )
        if existing is not None and existing.filing_status is DocumentFilingStatus.FILED:
            transition = self.lineage_repository.get_state_transition(
                policy_evaluation_id=evaluation.id,
                affected_entity_type=DOCUMENT_FILING_ENTITY_TYPE,
                affected_entity_id=attachment.id,
            )
            return DocumentFilingOutcome(
                attachment_id=attachment.id,
                project_id=project_id,
                document_id=existing.id,
                state_transition_id=transition.id if transition is not None else None,
                status=DocumentFilingOutcomeStatus.ALREADY_FILED,
            )

        try:
            content = self.content_loader(event, attachment)
        except AttachmentContentUnavailable:
            return DocumentFilingOutcome(
                attachment_id=attachment.id,
                project_id=project_id,
                status=DocumentFilingOutcomeStatus.SKIPPED,
                skip_reason=DocumentFilingSkipReason.ATTACHMENT_CONTENT_UNAVAILABLE,
            )
        content_hash = hashlib.sha256(content).hexdigest()
        if attachment.content_hash is None or attachment.content_hash != content_hash:
            return DocumentFilingOutcome(
                attachment_id=attachment.id,
                project_id=project_id,
                status=DocumentFilingOutcomeStatus.SKIPPED,
                skip_reason=DocumentFilingSkipReason.ATTACHMENT_CONTENT_MISMATCH,
            )

        document, transition = self._ensure_preview(
            attachment=attachment,
            project_id=project_id,
            proposal_id=proposal_id,
            evaluation=evaluation,
            authorization=authorization,
            content_hash=content_hash,
        )
        if document.filing_status is DocumentFilingStatus.FILED:
            return DocumentFilingOutcome(
                attachment_id=attachment.id,
                project_id=project_id,
                document_id=document.id,
                state_transition_id=transition.id,
                status=DocumentFilingOutcomeStatus.ALREADY_FILED,
            )

        document = self.document_repository.get_for_update(document.id)
        transition = self.lineage_repository.get_state_transition_for_update(
            policy_evaluation_id=evaluation.id,
            affected_entity_type=DOCUMENT_FILING_ENTITY_TYPE,
            affected_entity_id=attachment.id,
        )
        if document is None or transition is None:
            raise DocumentFilingIntegrityError("document filing preview disappeared")
        if document.filing_status is DocumentFilingStatus.FILED:
            self.session.commit()
            return DocumentFilingOutcome(
                attachment_id=attachment.id,
                project_id=project_id,
                document_id=document.id,
                state_transition_id=transition.id,
                status=DocumentFilingOutcomeStatus.ALREADY_FILED,
            )

        project = self.project_repository.get(project_id)
        if project is None:
            raise DocumentFilingIntegrityError("authorized project was not found")
        try:
            drive_file = self._ensure_drive_file(
                document_id=document.id,
                project=project,
                attachment=attachment,
                content=content,
                content_hash=content_hash,
            )
        except DriveProviderError:
            self.document_repository.mark_retryable_failure(
                document,
                failure_code=DOCUMENT_FILING_FAILURE_CODE,
            )
            self.session.commit()
            return DocumentFilingOutcome(
                attachment_id=attachment.id,
                project_id=project_id,
                document_id=document.id,
                state_transition_id=transition.id,
                status=DocumentFilingOutcomeStatus.RETRYABLE_FAILURE,
                failure_code=DOCUMENT_FILING_FAILURE_CODE,
            )

        if document.filing_status is not DocumentFilingStatus.FILED:
            filed_at = datetime.now(UTC)
            self.document_repository.mark_filed(
                document,
                drive_file_id=drive_file.file_id,
                drive_parent_folder_id=drive_file.parent_folder_id,
                filed_at=filed_at,
            )
            if transition.status is TransitionStatus.PREVIEWED:
                self.lineage_repository.mark_transition_applied(
                    transition,
                    applied_at=filed_at,
                )
            self._ensure_audit(event, project_id, proposal_id, evaluation, transition, document)
            self.session.commit()
        return DocumentFilingOutcome(
            attachment_id=attachment.id,
            project_id=project_id,
            document_id=document.id,
            state_transition_id=transition.id,
            status=DocumentFilingOutcomeStatus.FILED,
        )

    def _ensure_preview(
        self,
        *,
        attachment: Attachment,
        project_id: UUID,
        proposal_id: UUID,
        evaluation: PolicyEvaluation,
        authorization: DocumentFilingAuthorization,
        content_hash: str,
    ):
        document = self.document_repository.get_by_project_attachment(
            project_id=project_id,
            source_attachment_id=attachment.id,
            for_update=True,
        )
        if document is None:
            document = self.document_repository.create_pending(
                project_id=project_id,
                source_attachment_id=attachment.id,
                filename=attachment.filename,
                category=self.default_category,
                content_hash=content_hash,
            )
        elif document.content_hash != content_hash:
            raise DocumentFilingIntegrityError("document content hash changed")

        transition = self.lineage_repository.get_state_transition_for_update(
            policy_evaluation_id=evaluation.id,
            affected_entity_type=DOCUMENT_FILING_ENTITY_TYPE,
            affected_entity_id=attachment.id,
        )
        if transition is None:
            effect = DocumentFilingEffect(
                document_id=document.id,
                attachment_id=attachment.id,
                project_id=project_id,
                filename=attachment.filename,
                category=self.default_category,
                content_hash=content_hash,
                authorization=authorization,
            )
            evidence = self.lineage_repository.list_policy_evidence(evaluation.id)
            transition = self.lineage_repository.create_transition(
                ai_proposal_id=proposal_id,
                policy_evaluation_id=evaluation.id,
                affected_entity_type=DOCUMENT_FILING_ENTITY_TYPE,
                affected_entity_id=attachment.id,
                current_state={"filing_status": None},
                proposed_state={
                    "filing_status": DocumentFilingStatus.FILED.value,
                    "project_id": str(project_id),
                    "category": self.default_category,
                },
                requirement_effects=[],
                document_effects=[effect.model_dump(mode="json")],
                follow_up_effects=[],
                disposition=TransitionDisposition.AUTO_APPLY,
                evidence_item_ids=tuple(item.id for item in evidence),
            )
        self.session.commit()
        return document, transition

    def _ensure_drive_file(
        self,
        *,
        document_id: UUID,
        project: Project,
        attachment: Attachment,
        content: bytes,
        content_hash: str,
    ):
        root_id = self.drive_client.ensure_folder(
            name=self.root_folder_name,
            parent_folder_id=None,
            app_properties={"tracework_kind": "root"},
        )
        project_folder_id = self.drive_client.ensure_folder(
            name=sanitize_drive_name(f"{project.project_code} - {project.name}"),
            parent_folder_id=root_id,
            app_properties={
                "tracework_kind": "project",
                "tracework_project_id": str(project.id),
            },
        )
        category_id = self.drive_client.ensure_folder(
            name=self.default_category,
            parent_folder_id=project_folder_id,
            app_properties={
                "tracework_kind": "category",
                "tracework_project_id": str(project.id),
                "tracework_category": self.default_category,
            },
        )
        properties = {
            "tracework_kind": "document",
            "tracework_document_id": str(document_id),
            "tracework_attachment_id": str(attachment.id),
            "tracework_content_hash": content_hash,
        }
        existing = self.drive_client.find_file(
            parent_folder_id=category_id,
            app_properties=properties,
        )
        if existing is not None:
            return existing
        return self.drive_client.upload_file(
            name=sanitize_drive_name(attachment.filename),
            mime_type=attachment.mime_type,
            content=content,
            parent_folder_id=category_id,
            app_properties=properties,
        )

    def _ensure_audit(self, event, project_id, proposal_id, evaluation, transition, document):
        if self.lineage_repository.get_audit_event_for_transition(
            event_type=DOCUMENT_FILED_AUDIT_EVENT,
            state_transition_id=transition.id,
        ) is not None:
            return
        self.lineage_repository.create_audit_event(
            event_type=DOCUMENT_FILED_AUDIT_EVENT,
            actor_type="system",
            correspondence_event_id=event.id,
            project_id=project_id,
            ai_proposal_id=proposal_id,
            policy_evaluation_id=evaluation.id,
            state_transition_id=transition.id,
            details={
                "document_id": str(document.id),
                "attachment_id": str(document.source_attachment_id),
                "drive_file_id": document.drive_file_id,
                "filename": document.filename,
                "category": document.category,
                "content_hash": document.content_hash,
            },
        )

    @staticmethod
    def _all_skipped(correspondence_event_id, attachments, reason):
        return CorrespondenceDocumentFilingResult(
            correspondence_event_id=correspondence_event_id,
            outcomes=tuple(
                DocumentFilingOutcome(
                    attachment_id=item.id,
                    status=DocumentFilingOutcomeStatus.SKIPPED,
                    skip_reason=reason,
                )
                for item in attachments
            ),
        )
