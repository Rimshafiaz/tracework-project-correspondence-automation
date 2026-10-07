import argparse
import asyncio
from uuid import UUID

from app.ai.requirement_reconciler import build_requirement_reconciler_agent
from app.ai.resolver import build_project_resolver_agent
from app.adapters.gmail.client import create_gmail_client
from app.adapters.gmail.attachment_content import download_gmail_attachment
from app.adapters.drive.client import create_drive_client
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.enums import AttachmentProcessingState
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.document import DocumentRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.core_correspondence_workflow import (
    CoreCorrespondenceWorkflowResult,
    CoreCorrespondenceWorkflowService,
)
from app.services.gmail_attachment_preparation import GmailAttachmentPreparationService
from app.services.policy.project_identity_authorization import ProjectIdentityAuthorizationService
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationService
from app.services.policy.requirement_context import RequirementPolicyContextService
from app.services.project_resolution import ProjectResolutionService
from app.services.project_resolution_context import ProjectResolutionContextService
from app.services.project_resolution_review_creation import ProjectResolutionReviewCreationService
from app.services.project_resolution_workflow import ProjectResolutionWorkflowService
from app.services.requirement_policy_workflow import RequirementPolicyWorkflowService
from app.services.requirement_reconciliation import RequirementReconciliationService
from app.services.requirement_reconciliation_context import RequirementReconciliationContextService
from app.services.requirement_review_creation import RequirementReviewCreationService
from app.services.document_filing import AttachmentContentUnavailable, DocumentFilingService


async def process_correspondence_event(
    correspondence_event_id: UUID,
    settings: Settings | None = None,
) -> CoreCorrespondenceWorkflowResult:
    settings = settings or get_settings()
    session = SessionLocal()
    try:
        correspondence = CorrespondenceEventRepository(session)
        attachments = AttachmentRepository(session)
        projects = ProjectRepository(session)
        identifiers = ProjectIdentifierRepository(session)
        contacts = ProjectContactRepository(session)
        links = CorrespondenceProjectLinkRepository(session)
        requirements = RequirementRepository(session)
        lineage = LineageRepository(session)
        reviews = ReviewItemRepository(session)

        event = correspondence.get(correspondence_event_id)
        if event is None:
            raise LookupError("correspondence event was not found")
        pending_attachments = tuple(
            attachment
            for attachment in attachments.list_for_correspondence_event(event.id)
            if attachment.processing_state is AttachmentProcessingState.PENDING
        )
        gmail_service = None
        if event.source == "gmail" and (pending_attachments or settings.drive_enabled):
            if settings.drive_enabled:
                drive_client = create_drive_client(settings)
            else:
                drive_client = None
            gmail_service = create_gmail_client(settings)
        else:
            drive_client = create_drive_client(settings) if settings.drive_enabled else None

        if event.source == "gmail" and pending_attachments:
            GmailAttachmentPreparationService(
                gmail_service=gmail_service,
                settings=settings,
                correspondence_repository=correspondence,
                attachment_repository=attachments,
            ).process(event.id)
            session.commit()

        def load_attachment_content(source_event, attachment):
            if source_event.source != "gmail" or gmail_service is None:
                raise AttachmentContentUnavailable(
                    "attachment source cannot be downloaded by the configured adapter"
                )
            try:
                return download_gmail_attachment(
                    gmail_service,
                    attachment_id=attachment.id,
                    message_id=source_event.external_event_id,
                    source_attachment_id=attachment.source_attachment_id,
                    declared_size_bytes=attachment.size_bytes,
                    max_size_bytes=settings.attachment_max_size_bytes,
                ).content
            except Exception as exc:
                raise AttachmentContentUnavailable(
                    "attachment content could not be loaded"
                ) from exc

        project_authorization = ProjectIdentityAuthorizationService(
            session=session,
            lineage_repository=lineage,
            project_identifier_repository=identifiers,
            project_contact_repository=contacts,
            project_link_repository=links,
        )
        project_workflow = ProjectResolutionWorkflowService(
            authorization_service=project_authorization,
            review_creation_service=ProjectResolutionReviewCreationService(
                session=session,
                lineage_repository=lineage,
                review_repository=reviews,
                project_link_repository=links,
            ),
        )
        requirement_context = RequirementReconciliationContextService(
            project_link_repository=links,
            correspondence_repository=correspondence,
            requirement_repository=requirements,
            attachment_repository=attachments,
            lineage_repository=lineage,
            max_requirements=settings.requirement_reconciler_max_requirements,
            max_attachments=settings.requirement_reconciler_max_attachments,
            max_source_characters=(
                settings.requirement_reconciler_max_source_characters
            ),
        )
        requirement_policy_context = RequirementPolicyContextService(
            correspondence_repository=correspondence,
            project_link_repository=links,
            requirement_repository=requirements,
            attachment_repository=attachments,
            lineage_repository=lineage,
        )
        requirement_workflow = RequirementPolicyWorkflowService(
            authorization_service=RequirementPolicyAuthorizationService(
                session=session,
                context_service=requirement_policy_context,
                lineage_repository=lineage,
                requirement_repository=requirements,
            ),
            review_creation_service=RequirementReviewCreationService(
                session=session,
                lineage_repository=lineage,
                requirement_repository=requirements,
                review_repository=reviews,
            ),
        )
        workflow = CoreCorrespondenceWorkflowService(
            session=session,
            correspondence_repository=correspondence,
            project_link_repository=links,
            lineage_repository=lineage,
            project_context_service=ProjectResolutionContextService(
                correspondence_repository=correspondence,
                attachment_repository=attachments,
                project_repository=projects,
                identifier_repository=identifiers,
                contact_repository=contacts,
                project_link_repository=links,
            ),
            project_resolution_service=ProjectResolutionService(
                agent=build_project_resolver_agent(settings),
                lineage_repository=lineage,
                model_identifier=settings.project_resolver_model,
            ),
            project_workflow_service=project_workflow,
            requirement_context_service=requirement_context,
            requirement_reconciliation_service=RequirementReconciliationService(
                agent=build_requirement_reconciler_agent(settings),
                lineage_repository=lineage,
                model_identifier=settings.requirement_reconciler_model,
            ),
            requirement_workflow_service=requirement_workflow,
            document_filing_service=(
                DocumentFilingService(
                    session=session,
                    drive_client=drive_client,
                    root_folder_name=settings.drive_root_folder_name,
                    default_category=settings.drive_default_category_folder,
                    content_loader=load_attachment_content,
                    attachment_repository=attachments,
                    document_repository=DocumentRepository(session),
                    project_repository=projects,
                    project_link_repository=links,
                    review_repository=reviews,
                    lineage_repository=lineage,
                )
                if drive_client is not None
                else None
            ),
        )
        return await workflow.process(correspondence_event_id)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process one persisted correspondence event through the core workflow."
    )
    parser.add_argument("correspondence_event_id", type=UUID)
    args = parser.parse_args()
    result = asyncio.run(process_correspondence_event(args.correspondence_event_id))
    print(
        f"Core processing {result.status.value}: "
        f"correspondence_event_id={result.correspondence_event_id}"
    )


if __name__ == "__main__":
    main()
