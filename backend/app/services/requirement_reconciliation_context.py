from uuid import UUID

from app.ai.schemas import ResolverCorrespondence
from app.contracts.requirement_reconciliation import ExistingRequirementEvidence, RequirementAttachmentContext, RequirementContextLimitKind, RequirementContextLimitOutcome, RequirementReconcilerInput, RequirementSnapshot
from app.models.attachment import Attachment
from app.models.evidence_item import EvidenceItem
from app.models.requirement import Requirement
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository


class AuthoritativeProjectLinkNotFound(LookupError):
    pass


class RequirementContextLimitExceeded(RuntimeError):
    def __init__(self, outcome: RequirementContextLimitOutcome) -> None:
        super().__init__(outcome.reason)
        self.outcome = outcome


class RequirementReconciliationContextService:
    def __init__(
        self,
        *,
        project_link_repository: CorrespondenceProjectLinkRepository,
        correspondence_repository: CorrespondenceEventRepository,
        requirement_repository: RequirementRepository,
        attachment_repository: AttachmentRepository,
        lineage_repository: LineageRepository,
        max_requirements: int,
        max_attachments: int,
        max_source_characters: int,
    ) -> None:
        limits = (max_requirements, max_attachments, max_source_characters)
        if any(limit <= 0 for limit in limits):
            raise ValueError("requirement reconciliation context limits must be positive")
        self.project_link_repository = project_link_repository
        self.correspondence_repository = correspondence_repository
        self.requirement_repository = requirement_repository
        self.attachment_repository = attachment_repository
        self.lineage_repository = lineage_repository
        self.max_requirements = max_requirements
        self.max_attachments = max_attachments
        self.max_source_characters = max_source_characters

    def build(
        self,
        authoritative_project_link_id: UUID,
    ) -> RequirementReconcilerInput:
        link = self.project_link_repository.get(authoritative_project_link_id)
        if link is None:
            raise AuthoritativeProjectLinkNotFound(
                "authoritative correspondence-project link was not found"
            )
        correspondence = self.correspondence_repository.get(
            link.correspondence_event_id
        )
        if correspondence is None:
            raise AuthoritativeProjectLinkNotFound(
                "linked correspondence event was not found"
            )

        requirements = tuple(
            self.requirement_repository.list_for_project(link.project_id)
        )
        self._enforce_limit(
            RequirementContextLimitKind.REQUIREMENT_COUNT,
            len(requirements),
            self.max_requirements,
        )
        attachments = tuple(
            self.attachment_repository.list_for_correspondence_event(
                correspondence.id
            )
        )
        self._enforce_limit(
            RequirementContextLimitKind.ATTACHMENT_COUNT,
            len(attachments),
            self.max_attachments,
        )
        requirement_ids = {requirement.id for requirement in requirements}
        evidence = tuple(
            self.lineage_repository.list_valid_evidence_for_requirements(
                project_id=link.project_id,
                requirement_ids=requirement_ids,
            )
        )
        source_characters = self._source_character_count(
            correspondence.subject,
            correspondence.body,
            requirements,
            attachments,
            evidence,
        )
        self._enforce_limit(
            RequirementContextLimitKind.SOURCE_CHARACTER_COUNT,
            source_characters,
            self.max_source_characters,
        )

        return RequirementReconcilerInput(
            project_id=link.project_id,
            authoritative_project_link_id=link.id,
            correspondence=ResolverCorrespondence(
                correspondence_event_id=correspondence.id,
                source=correspondence.source,
                external_conversation_id=correspondence.external_conversation_id,
                sender_identifier=correspondence.sender_identifier,
                sender_name=correspondence.sender_name,
                sender_email=correspondence.sender_email,
                subject=correspondence.subject,
                body=correspondence.body,
                received_at=correspondence.received_at,
            ),
            requirements=tuple(self._requirement_snapshot(item) for item in requirements),
            attachments=tuple(self._attachment_context(item) for item in attachments),
            existing_valid_evidence=tuple(
                self._evidence_context(item) for item in evidence
            ),
        )

    @staticmethod
    def _enforce_limit(
        kind: RequirementContextLimitKind,
        actual: int,
        configured: int,
    ) -> None:
        if actual <= configured:
            return
        raise RequirementContextLimitExceeded(
            RequirementContextLimitOutcome(
                limit_kind=kind,
                configured_limit=configured,
                actual_value=actual,
                reason=(
                    f"Requirement reconciliation context exceeds the configured "
                    f"{kind.value.lower()} limit."
                ),
            )
        )

    @staticmethod
    def _source_character_count(
        subject,
        body,
        requirements: tuple[Requirement, ...],
        attachments: tuple[Attachment, ...],
        evidence: tuple[EvidenceItem, ...],
    ) -> int:
        values = [subject, body]
        values.extend(requirement.name for requirement in requirements)
        values.extend(requirement.description for requirement in requirements)
        values.extend(attachment.extracted_text for attachment in attachments)
        values.extend(item.excerpt for item in evidence)
        return sum(len(value) for value in values if value is not None)

    @staticmethod
    def _requirement_snapshot(requirement: Requirement) -> RequirementSnapshot:
        return RequirementSnapshot(
            requirement_id=requirement.id,
            name=requirement.name,
            description=requirement.description,
            current_state=requirement.state,
            expected_date=requirement.expected_date,
        )

    @staticmethod
    def _attachment_context(attachment: Attachment) -> RequirementAttachmentContext:
        return RequirementAttachmentContext(
            attachment_id=attachment.id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            processing_state=attachment.processing_state,
            extracted_text=attachment.extracted_text,
            extraction_metadata=attachment.extraction_metadata,
            content_hash=attachment.content_hash,
        )

    @staticmethod
    def _evidence_context(evidence: EvidenceItem) -> ExistingRequirementEvidence:
        return ExistingRequirementEvidence(
            evidence_item_id=evidence.id,
            correspondence_event_id=evidence.correspondence_event_id,
            project_id=evidence.project_id,
            requirement_id=evidence.requirement_id,
            attachment_id=evidence.attachment_id,
            source_type=evidence.source_type,
            excerpt=evidence.excerpt,
            page_number=evidence.page_number,
            section=evidence.section,
            validity=evidence.validity,
        )
