import argparse
from uuid import UUID

from app.adapters.drive.client import create_drive_client
from app.adapters.gmail.attachment_content import download_gmail_attachment
from app.adapters.gmail.client import create_gmail_client
from app.contracts.document_filing import CorrespondenceDocumentFilingResult, DocumentFilingOutcomeStatus
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.enums import ProposalType
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.document import DocumentRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.document_filing import AttachmentContentUnavailable, DocumentFilingService
from app.services.document_revision import DocumentRevisionService
from app.services.policy.project_identity_rules import PROJECT_IDENTITY_POLICY_VERSION


def retry_document_filing(
    proposal_id: UUID,
    policy_evaluation_id: UUID,
    settings: Settings | None = None,
) -> CorrespondenceDocumentFilingResult:
    """Retry filing from persisted authorization without running the core workflow."""
    settings = settings or get_settings()
    session = SessionLocal()
    try:
        lineage = LineageRepository(session)
        proposal = lineage.get_proposal(proposal_id)
        evaluation = lineage.get_policy_evaluation_by_id(policy_evaluation_id)
        if (
            proposal is None
            or proposal.proposal_type is not ProposalType.PROJECT_RESOLUTION
            or evaluation is None
            or evaluation.ai_proposal_id != proposal_id
            or evaluation.policy_version != PROJECT_IDENTITY_POLICY_VERSION
        ):
            raise ValueError("a persisted project-resolution proposal and its project policy are required")

        # Drive authorization upgrades the shared token scopes before Gmail uses it.
        drive_client = create_drive_client(settings)
        gmail_service = None

        def load_attachment_content(event, attachment):
            nonlocal gmail_service
            if event.source != "gmail":
                raise AttachmentContentUnavailable("attachment source is unsupported")
            try:
                if gmail_service is None:
                    gmail_service = create_gmail_client(settings)
                return download_gmail_attachment(
                    gmail_service,
                    attachment_id=attachment.id,
                    message_id=event.external_event_id,
                    source_attachment_id=attachment.source_attachment_id,
                    declared_size_bytes=attachment.size_bytes,
                    max_size_bytes=settings.attachment_max_size_bytes,
                ).content
            except Exception as exc:
                raise AttachmentContentUnavailable("attachment content could not be loaded") from exc

        documents = DocumentRepository(session)
        reviews = ReviewItemRepository(session)
        service = DocumentFilingService(
            session=session,
            drive_client=drive_client,
            root_folder_name=settings.drive_root_folder_name,
            default_category=settings.drive_default_category_folder,
            content_loader=load_attachment_content,
            attachment_repository=AttachmentRepository(session),
            document_repository=documents,
            project_repository=ProjectRepository(session),
            project_link_repository=CorrespondenceProjectLinkRepository(session),
            review_repository=reviews,
            lineage_repository=lineage,
            revision_service=DocumentRevisionService(
                session=session,
                document_repository=documents,
                lineage_repository=lineage,
                review_repository=reviews,
            ),
        )
        return service.file_for_project_resolution(
            proposal_id=proposal_id,
            policy_evaluation_id=policy_evaluation_id,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry document filing using persisted project authorization.")
    parser.add_argument("proposal_id", type=UUID)
    parser.add_argument("policy_evaluation_id", type=UUID)
    args = parser.parse_args()
    try:
        result = retry_document_filing(args.proposal_id, args.policy_evaluation_id)
    except Exception:
        parser.exit(1, "Document filing retry failed. Check backend configuration and persisted authorization.\n")
    for outcome in result.outcomes:
        reason = outcome.skip_reason.value if outcome.skip_reason is not None else outcome.failure_code
        print(f"Attachment {outcome.attachment_id}: {outcome.status.value}" + (f" ({reason})" if reason else ""))
    if any(item.status in {DocumentFilingOutcomeStatus.RETRYABLE_FAILURE, DocumentFilingOutcomeStatus.SKIPPED} for item in result.outcomes):
        parser.exit(1)


if __name__ == "__main__":
    main()
