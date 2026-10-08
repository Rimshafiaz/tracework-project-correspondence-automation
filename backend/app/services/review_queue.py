from uuid import UUID

from pydantic import ValidationError

from app.contracts.project_resolution_review_queue import (
    ProjectResolutionReviewCorrespondence,
)
from app.contracts.review_queue import (
    PROJECT_RESOLUTION_ALLOWED_ACTIONS,
    REQUIREMENT_REVIEW_ALLOWED_ACTIONS,
    DocumentRevisionCurrentDocument,
    DocumentRevisionReviewAttachment,
    DocumentRevisionReviewDocument,
    DocumentRevisionReviewReadDetail,
    NewRequirementReviewReadDetail,
    ProjectResolutionReviewReadDetail,
    RequirementChangeReviewReadDetail,
    ReviewQueueSummary,
    ReviewReadDetail,
)
from app.models.enums import ReviewStatus, ReviewType
from app.models.enums import DocumentRevisionStatus, TransitionDisposition, TransitionStatus
from app.contracts.document_revision import (
    DOCUMENT_REVISION_POLICY_VERSION,
    DocumentRevisionEffect,
    RevisionOutcome,
)
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.review_item import ReviewItemRepository
from app.repositories.document import DocumentRepository
from app.repositories.project import ProjectRepository
from app.services.policy.requirement_review_handoff import (
    RequirementReviewHandoffError,
    RequirementReviewHandoffService,
)
from app.services.project_resolution_review_query import (
    ProjectResolutionReviewQueryError,
    ProjectResolutionReviewQueryService,
)

SUPPORTED_REVIEW_TYPES = {
    ReviewType.PROJECT_RESOLUTION,
    ReviewType.REQUIREMENT_CHANGE,
    ReviewType.NEW_REQUIREMENT,
    ReviewType.DOCUMENT_REVISION,
}


class ReviewQueueNotFoundError(LookupError):
    pass


class ReviewQueueIntegrityError(RuntimeError):
    pass


class ReviewQueueQueryService:
    def __init__(
        self,
        *,
        review_repository: ReviewItemRepository,
        correspondence_repository: CorrespondenceEventRepository,
        project_resolution_query_service: ProjectResolutionReviewQueryService,
        requirement_handoff_service: RequirementReviewHandoffService,
        attachment_repository: AttachmentRepository,
        document_repository: DocumentRepository,
        project_repository: ProjectRepository,
    ) -> None:
        self.review_repository = review_repository
        self.correspondence_repository = correspondence_repository
        self.project_resolution_query_service = project_resolution_query_service
        self.requirement_handoff_service = requirement_handoff_service
        self.attachment_repository = attachment_repository
        self.document_repository = document_repository
        self.project_repository = project_repository

    def list_pending(self) -> tuple[ReviewQueueSummary, ...]:
        return tuple(
            self._summary(review)
            for review in self.review_repository.list_pending(SUPPORTED_REVIEW_TYPES)
        )

    def get_detail(self, review_item_id: UUID) -> ReviewReadDetail:
        review = self.review_repository.get(review_item_id)
        if review is None or review.review_type not in SUPPORTED_REVIEW_TYPES:
            raise ReviewQueueNotFoundError("review item was not found")

        if review.review_type is ReviewType.PROJECT_RESOLUTION:
            try:
                detail = self.project_resolution_query_service.get_detail(
                    review_item_id
                )
            except ProjectResolutionReviewQueryError as exc:
                raise ReviewQueueIntegrityError(
                    "project-resolution review history is inconsistent"
                ) from exc
            return ProjectResolutionReviewReadDetail(
                allowed_actions=self._allowed_actions(review),
                detail=detail,
            )

        if review.review_type is ReviewType.DOCUMENT_REVISION:
            return self._document_revision_detail(review)

        transition = self.review_repository.get_state_transition(
            review.state_transition_id
        )
        if transition is None:
            raise ReviewQueueIntegrityError(
                "requirement review transition is inconsistent"
            )
        try:
            handoff = self.requirement_handoff_service.load(
                transition.policy_evaluation_id
            )
        except RequirementReviewHandoffError as exc:
            raise ReviewQueueIntegrityError(
                "requirement review history is inconsistent"
            ) from exc
        if (
            handoff.state_transition_id != transition.id
            or handoff.correspondence_event_id != review.correspondence_event_id
        ):
            raise ReviewQueueIntegrityError(
                "requirement review history is inconsistent"
            )
        correspondence = self.correspondence_repository.get(
            review.correspondence_event_id
        )
        if correspondence is None:
            raise ReviewQueueIntegrityError(
                "requirement review correspondence is inconsistent"
            )
        correspondence_context = ProjectResolutionReviewCorrespondence(
            correspondence_event_id=correspondence.id,
            source=correspondence.source,
            sender_identifier=correspondence.sender_identifier,
            sender_email=correspondence.sender_email,
            sender_name=correspondence.sender_name,
            subject=correspondence.subject,
            body=correspondence.body,
            received_at=correspondence.received_at,
        )
        summary = self._summary(review)
        detail_type = (
            NewRequirementReviewReadDetail
            if review.review_type is ReviewType.NEW_REQUIREMENT
            else RequirementChangeReviewReadDetail
        )
        return detail_type(
            allowed_actions=self._allowed_actions(review),
            review=summary,
            correspondence=correspondence_context,
            handoff=handoff,
        )

    def _document_revision_detail(self, review) -> DocumentRevisionReviewReadDetail:
        transition = self.review_repository.get_state_transition(
            review.state_transition_id
        )
        if (
            transition is None
            or transition.affected_entity_type != "document_revision"
            or transition.status is not TransitionStatus.PREVIEWED
            or transition.disposition is not TransitionDisposition.REVIEW
            or len(transition.document_effects) != 1
        ):
            raise ReviewQueueIntegrityError(
                "document revision review history is inconsistent"
            )
        try:
            effect = DocumentRevisionEffect.model_validate(
                transition.document_effects[0]
            )
        except ValidationError as exc:
            raise ReviewQueueIntegrityError(
                "document revision review history is inconsistent"
            ) from exc
        if (
            effect.document_id != transition.affected_entity_id
            or effect.incoming_outcome is not RevisionOutcome.REVIEW_REQUIRED
            or effect.policy_version != DOCUMENT_REVISION_POLICY_VERSION
        ):
            raise ReviewQueueIntegrityError(
                "document revision review history is inconsistent"
            )

        incoming = self.document_repository.get(effect.document_id)
        project = self.project_repository.get(effect.project_id)
        attachment = self.attachment_repository.get(effect.source_attachment_id)
        correspondence = self.correspondence_repository.get(
            review.correspondence_event_id
        )
        if (
            incoming is None
            or project is None
            or attachment is None
            or correspondence is None
            or incoming.revision_status is not DocumentRevisionStatus.REVIEW_REQUIRED
            or incoming.project_id != effect.project_id
            or incoming.source_attachment_id != effect.source_attachment_id
            or incoming.category != effect.category
            or incoming.document_family_key != effect.family_key
            or incoming.revision_label != effect.raw_revision_label
            or incoming.revision_normalized != effect.normalized_revision
            or incoming.revision_order != effect.revision_order
            or attachment.correspondence_event_id != review.correspondence_event_id
        ):
            raise ReviewQueueIntegrityError(
                "document revision review history is inconsistent"
            )

        current_detail = None
        if effect.previous_current_document_id is not None:
            current = self.document_repository.get(
                effect.previous_current_document_id
            )
            if (
                current is None
                or current.project_id != incoming.project_id
                or current.category != incoming.category
                or current.document_family_key != effect.family_key
                or current.revision_status is not DocumentRevisionStatus.CURRENT
                or current.revision_normalized is None
                or current.revision_order is None
            ):
                raise ReviewQueueIntegrityError(
                    "document revision current state is inconsistent"
                )
            current_detail = DocumentRevisionCurrentDocument(
                document_id=current.id,
                revision_normalized=current.revision_normalized,
                revision_order=current.revision_order,
                content_hash=current.content_hash,
            )

        return DocumentRevisionReviewReadDetail(
            review=self._summary(review),
            correspondence=ProjectResolutionReviewCorrespondence(
                correspondence_event_id=correspondence.id,
                source=correspondence.source,
                sender_identifier=correspondence.sender_identifier,
                sender_email=correspondence.sender_email,
                sender_name=correspondence.sender_name,
                subject=correspondence.subject,
                body=correspondence.body,
                received_at=correspondence.received_at,
            ),
            attachment=DocumentRevisionReviewAttachment(
                attachment_id=attachment.id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                content_hash=attachment.content_hash,
            ),
            state_transition_id=transition.id,
            transition_status=transition.status,
            disposition=transition.disposition,
            incoming_document=DocumentRevisionReviewDocument(
                document_id=incoming.id,
                source_attachment_id=incoming.source_attachment_id,
                filename=incoming.filename,
                project_id=project.id,
                project_code=project.project_code,
                project_name=project.name,
                category=incoming.category,
                document_family_key=incoming.document_family_key,
                revision_label=incoming.revision_label,
                revision_normalized=incoming.revision_normalized,
                revision_order=incoming.revision_order,
                content_hash=incoming.content_hash,
            ),
            current_document=current_detail,
            reasons=effect.reasons,
            triggered_rule_ids=effect.triggered_rule_ids,
        )

    @classmethod
    def _summary(cls, review) -> ReviewQueueSummary:
        return ReviewQueueSummary(
            review_item_id=review.id,
            correspondence_event_id=review.correspondence_event_id,
            review_type=review.review_type,
            status=review.status,
            review_reason=review.review_reason,
            created_at=review.created_at,
            resolved_at=review.resolved_at,
            allowed_actions=cls._allowed_actions(review),
        )

    @staticmethod
    def _allowed_actions(review):
        if review.status is not ReviewStatus.PENDING:
            return ()
        if review.review_type is ReviewType.PROJECT_RESOLUTION:
            return PROJECT_RESOLUTION_ALLOWED_ACTIONS
        if review.review_type in {
            ReviewType.REQUIREMENT_CHANGE,
            ReviewType.NEW_REQUIREMENT,
        }:
            return REQUIREMENT_REVIEW_ALLOWED_ACTIONS
        return ()
