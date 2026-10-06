import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from app.ai.schemas import ProjectResolverInput, ResolverAttachment, ResolverCorrespondence
from app.contracts.project_candidate import (
    CandidateIdentifierHint,
    CandidateSignalSource,
    CandidateValueHint,
    ProjectCandidateQuery,
)
from app.models.enums import AttachmentProcessingState
from app.normalization.project_identity import normalize_project_name
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.project_candidate_retrieval import (
    PROJECT_ALIAS_IDENTIFIER_TYPE,
    retrieve_project_candidates,
)


class ProjectResolutionContextError(RuntimeError):
    pass


class CorrespondenceEventNotFound(ProjectResolutionContextError):
    pass


class AttachmentContextNotReady(ProjectResolutionContextError):
    pass


@dataclass(frozen=True)
class _SourceText:
    text: str
    source: CandidateSignalSource
    attachment_id: UUID | None = None


class ProjectResolutionContextService:
    """Build the deterministic M7 snapshot and bounded M8 input for one event."""

    def __init__(
        self,
        *,
        correspondence_repository: CorrespondenceEventRepository,
        attachment_repository: AttachmentRepository,
        project_repository: ProjectRepository,
        identifier_repository: ProjectIdentifierRepository,
        contact_repository: ProjectContactRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
    ) -> None:
        self.correspondence_repository = correspondence_repository
        self.attachment_repository = attachment_repository
        self.project_repository = project_repository
        self.identifier_repository = identifier_repository
        self.contact_repository = contact_repository
        self.project_link_repository = project_link_repository

    def build(self, correspondence_event_id: UUID) -> ProjectResolverInput:
        event = self.correspondence_repository.get(correspondence_event_id)
        if event is None:
            raise CorrespondenceEventNotFound("correspondence event was not found")

        attachments = tuple(
            self.attachment_repository.list_for_correspondence_event(event.id)
        )
        pending = [
            attachment
            for attachment in attachments
            if attachment.processing_state is AttachmentProcessingState.PENDING
        ]
        if pending:
            raise AttachmentContextNotReady(
                "attachment extraction is not complete for this correspondence event"
            )

        sources = [
            _SourceText(event.subject or "", CandidateSignalSource.CORRESPONDENCE_EVENT),
            _SourceText(event.body, CandidateSignalSource.CORRESPONDENCE_EVENT),
        ]
        sources.extend(
            _SourceText(
                attachment.extracted_text,
                CandidateSignalSource.ATTACHMENT,
                attachment.id,
            )
            for attachment in attachments
            if attachment.extracted_text
        )

        project_codes: list[CandidateValueHint] = []
        normalized_names: list[CandidateValueHint] = []
        identifiers: list[CandidateIdentifierHint] = []

        for project in self.project_repository.list_all():
            for source in sources:
                if self._contains(source.text, project.project_code):
                    project_codes.append(self._value_hint(project.project_code, source))
                if self._contains(source.text, project.name):
                    normalized_names.append(
                        self._value_hint(normalize_project_name(project.name), source)
                    )

        for identifier, _project in self.identifier_repository.list_all_verified_with_projects():
            for source in sources:
                if not self._contains(source.text, identifier.display_value):
                    continue
                if identifier.identifier_type == PROJECT_ALIAS_IDENTIFIER_TYPE:
                    normalized_names.append(
                        self._value_hint(identifier.normalized_value, source)
                    )
                else:
                    identifiers.append(
                        CandidateIdentifierHint(
                            identifier_type=identifier.identifier_type,
                            normalized_value=identifier.normalized_value,
                            source=source.source,
                            attachment_id=source.attachment_id,
                        )
                    )

        query = ProjectCandidateQuery(
            source=event.source,
            external_conversation_id=event.external_conversation_id,
            sender_email_normalized=event.sender_email,
            project_codes=tuple(project_codes),
            normalized_names=tuple(normalized_names),
            identifiers=tuple(identifiers),
        )
        candidates = retrieve_project_candidates(
            query,
            project_repository=self.project_repository,
            identifier_repository=self.identifier_repository,
            contact_repository=self.contact_repository,
            conversation_repository=self.project_link_repository,
        )
        return ProjectResolverInput(
            correspondence=ResolverCorrespondence(
                correspondence_event_id=event.id,
                source=event.source,
                external_conversation_id=event.external_conversation_id,
                sender_identifier=event.sender_identifier,
                sender_name=event.sender_name,
                sender_email=event.sender_email,
                subject=event.subject,
                body=event.body,
                received_at=event.received_at,
            ),
            candidates=candidates,
            attachments=tuple(
                ResolverAttachment(
                    attachment_id=attachment.id,
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                    processing_state=attachment.processing_state,
                    extracted_text=attachment.extracted_text,
                    extraction_metadata=attachment.extraction_metadata,
                )
                for attachment in attachments
            ),
        )

    @staticmethod
    def _value_hint(value: str, source: _SourceText) -> CandidateValueHint:
        return CandidateValueHint(
            normalized_value=value,
            source=source.source,
            attachment_id=source.attachment_id,
        )

    @staticmethod
    def _contains(source_text: str, identity_value: str) -> bool:
        source = re.sub(
            r"\s+",
            " ",
            unicodedata.normalize("NFKC", source_text).casefold(),
        )
        value = re.sub(
            r"\s+",
            " ",
            unicodedata.normalize("NFKC", identity_value).casefold(),
        ).strip()
        if not value:
            return False
        return re.search(
            rf"(?<![\w]){re.escape(value)}(?![\w])",
            source,
        ) is not None
