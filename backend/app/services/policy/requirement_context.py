import hashlib
import json

from pydantic import ValidationError

from app.ai.requirement_schemas import RequirementReconciliation
from app.contracts.requirement_policy import AuthoritativeProjectLinkRecord, RequirementCurrentEvidenceSnapshot, RequirementCurrentRecord, RequirementPolicyContext, RequirementPolicyEvidenceFact, RequirementPolicyRule
from app.contracts.requirement_reconciliation import RequirementAttachmentSnapshot, RequirementContextSnapshotError, reconstruct_requirement_context_snapshot
from app.models.ai_proposal import AIProposal
from app.models.enums import ProposalType
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository


class RequirementPolicyContextError(ValueError):
    def __init__(self, rule: RequirementPolicyRule, message: str) -> None:
        super().__init__(message)
        self.rule = rule


class RequirementPolicyContextService:
    def __init__(
        self,
        *,
        correspondence_repository: CorrespondenceEventRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
        requirement_repository: RequirementRepository,
        attachment_repository: AttachmentRepository,
        lineage_repository: LineageRepository,
    ) -> None:
        self.correspondence_repository = correspondence_repository
        self.project_link_repository = project_link_repository
        self.requirement_repository = requirement_repository
        self.attachment_repository = attachment_repository
        self.lineage_repository = lineage_repository

    def build(
        self,
        proposal: AIProposal,
        *,
        lock_current_requirements: bool = False,
    ) -> RequirementPolicyContext:
        if proposal.proposal_type is not ProposalType.REQUIREMENT_RECONCILIATION:
            raise RequirementPolicyContextError(
                RequirementPolicyRule.PROPOSAL_TYPE_INVALID,
                "proposal type is not REQUIREMENT_RECONCILIATION",
            )
        try:
            reconciliation = RequirementReconciliation.model_validate(
                proposal.structured_output
            )
        except ValidationError as exc:
            raise RequirementPolicyContextError(
                RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED,
                "persisted requirement reconciliation is invalid",
            ) from exc
        try:
            snapshot = reconstruct_requirement_context_snapshot(
                proposal.input_metadata
            )
        except RequirementContextSnapshotError as exc:
            raise RequirementPolicyContextError(
                RequirementPolicyRule.CONTEXT_SNAPSHOT_MISSING,
                str(exc),
            ) from exc

        correspondence = self.correspondence_repository.get(
            proposal.correspondence_event_id
        )
        if correspondence is None:
            raise RequirementPolicyContextError(
                RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED,
                "proposal correspondence event is missing",
            )

        project_link = self.project_link_repository.get(
            snapshot.authoritative_project_link_id
        )
        list_requirements = (
            self.requirement_repository.list_for_project_for_update
            if lock_current_requirements
            else self.requirement_repository.list_for_project
        )
        current_requirements = list_requirements(snapshot.project_id)
        current_attachments = self.attachment_repository.list_for_correspondence_event(
            proposal.correspondence_event_id
        )
        snapshot_evidence = self.lineage_repository.list_evidence_by_ids(
            {item.evidence_item_id for item in snapshot.existing_evidence}
        )
        proposal_evidence = self.lineage_repository.list_proposal_evidence(
            proposal.id
        )

        return RequirementPolicyContext(
            proposal_id=proposal.id,
            proposal_type=proposal.proposal_type,
            correspondence_event_id=proposal.correspondence_event_id,
            reconciliation=reconciliation,
            m11_snapshot=snapshot,
            authoritative_project_link=(
                AuthoritativeProjectLinkRecord(
                    link_id=project_link.id,
                    correspondence_event_id=project_link.correspondence_event_id,
                    project_id=project_link.project_id,
                )
                if project_link is not None
                else None
            ),
            current_requirements=tuple(
                RequirementCurrentRecord(
                    requirement_id=requirement.id,
                    project_id=requirement.project_id,
                    name=requirement.name,
                    description=requirement.description,
                    state=requirement.state,
                    expected_date=requirement.expected_date,
                )
                for requirement in current_requirements
            ),
            current_subject_sha256=(
                self._sha256(correspondence.subject)
                if correspondence.subject is not None
                else None
            ),
            current_body_sha256=self._sha256(correspondence.body),
            current_attachments=tuple(
                self._attachment_snapshot(attachment)
                for attachment in current_attachments
            ),
            current_snapshot_evidence=tuple(
                RequirementCurrentEvidenceSnapshot(
                    evidence_item_id=evidence.id,
                    project_id=evidence.project_id,
                    requirement_id=evidence.requirement_id,
                    validity=evidence.validity,
                    excerpt_sha256=self._sha256(evidence.excerpt),
                )
                for evidence in snapshot_evidence
            ),
            proposal_evidence=tuple(
                RequirementPolicyEvidenceFact(
                    evidence_item_id=evidence.id,
                    correspondence_event_id=evidence.correspondence_event_id,
                    attachment_id=evidence.attachment_id,
                    project_id=evidence.project_id,
                    requirement_id=evidence.requirement_id,
                    source_type=evidence.source_type,
                    excerpt=evidence.excerpt,
                    page_number=evidence.page_number,
                    section=evidence.section,
                    provenance_metadata=evidence.provenance_metadata,
                    validity=evidence.validity,
                )
                for evidence in proposal_evidence
            ),
        )

    @classmethod
    def _attachment_snapshot(cls, attachment) -> RequirementAttachmentSnapshot:
        return RequirementAttachmentSnapshot(
            attachment_id=attachment.id,
            processing_state=attachment.processing_state.value,
            content_hash=attachment.content_hash,
            extracted_text_sha256=(
                cls._sha256(attachment.extracted_text)
                if attachment.extracted_text is not None
                else None
            ),
            extraction_metadata_sha256=(
                cls._sha256(
                    json.dumps(
                        attachment.extraction_metadata,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                if attachment.extraction_metadata is not None
                else None
            ),
        )

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
