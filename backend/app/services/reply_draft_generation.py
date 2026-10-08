import hashlib
import json
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.reply_drafter_context import ReplyDrafterRunTrace, ReplyDrafterToolName
from app.ai.reply_drafter_schemas import (
    ReplyDraftGroundingReference,
    ReplyDraftGroundingReferenceType,
    ReplyDraftProposal,
)
from app.contracts.reply_draft import ReplyDraftContent
from app.contracts.reply_draft_context import (
    FollowUpReplyScope,
    ReplyDraftEligibility,
    ReplyDraftEligibilityStatus,
)
from app.contracts.reply_draft_generation import (
    ReplyDraftGenerationResult,
    ReplyDraftGenerationStatus,
)
from app.models.enums import EvidenceValidity, ProposalType
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.document import DocumentRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.repositories.requirement import RequirementRepository
from app.services.reply_draft_eligibility import ReplyDraftEligibilityService
from app.services.reply_drafter_runner import ReplyDrafterRunner
from app.services.scoped_reply_draft_context import (
    ScopedReplyDraftContextService,
)

REPLY_DRAFT_GENERATED_AUDIT_EVENT = "reply_draft_generated"


class ReplyDraftGenerationError(RuntimeError):
    pass


class ReplyDraftGenerationNotDraftableError(ReplyDraftGenerationError):
    def __init__(self, eligibility: ReplyDraftEligibility) -> None:
        super().__init__("follow-up is not draftable in S2 V1")
        self.eligibility = eligibility


class ReplyDraftGroundingValidationError(ReplyDraftGenerationError):
    pass


class ReplyDraftGenerationStaleScopeError(ReplyDraftGenerationError):
    pass


class ReplyDraftGroundingValidator:
    """Validates only records exposed by the successful bounded tool trace."""

    _REQUIRED_TOOL = {
        ReplyDraftGroundingReferenceType.FOLLOW_UP: ReplyDrafterToolName.GET_DUE_FOLLOW_UP,
        ReplyDraftGroundingReferenceType.PROJECT: ReplyDrafterToolName.GET_PROJECT_SUMMARY,
        ReplyDraftGroundingReferenceType.REQUIREMENT: ReplyDrafterToolName.GET_REQUIREMENT_CONTEXT,
        ReplyDraftGroundingReferenceType.EVIDENCE: ReplyDrafterToolName.GET_REQUIREMENT_CONTEXT,
        ReplyDraftGroundingReferenceType.DOCUMENT: ReplyDrafterToolName.LIST_DOCUMENT_REVISION_STATUS,
    }

    def __init__(
        self,
        *,
        lineage_repository: LineageRepository,
        correspondence_repository: CorrespondenceEventRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
        document_repository: DocumentRepository,
    ) -> None:
        self.lineage = lineage_repository
        self.correspondence = correspondence_repository
        self.project_links = project_link_repository
        self.documents = document_repository

    def validate(
        self,
        *,
        proposal: ReplyDraftProposal,
        trace: ReplyDrafterRunTrace,
        scope: FollowUpReplyScope,
    ) -> tuple[UUID, ...]:
        if trace.follow_up_id != scope.follow_up_id:
            raise ReplyDraftGroundingValidationError(
                "successful tool trace belongs to a different follow-up"
            )
        exposed = self._exposed_references(trace)
        evidence_ids: list[UUID] = []
        for reference in proposal.grounding_references:
            if not self._was_exposed(reference, exposed):
                raise ReplyDraftGroundingValidationError(
                    "grounding reference was not returned by the successful tool run"
                )
            self._validate_scope_reference(reference, scope)
            if reference.reference_type is ReplyDraftGroundingReferenceType.EVIDENCE:
                evidence_ids.append(reference.record_id)
            elif reference.reference_type is ReplyDraftGroundingReferenceType.CORRESPONDENCE:
                self._validate_correspondence(reference.record_id, scope)
            elif reference.reference_type is ReplyDraftGroundingReferenceType.DOCUMENT:
                self._validate_document(reference.record_id, scope)

        self._validate_evidence(tuple(dict.fromkeys(evidence_ids)), scope)
        return tuple(dict.fromkeys(evidence_ids))

    @classmethod
    def _exposed_references(
        cls,
        trace: ReplyDrafterRunTrace,
    ) -> set[tuple[ReplyDrafterToolName, ReplyDraftGroundingReferenceType, UUID]]:
        return {
            (entry.tool_name, reference.reference_type, reference.record_id)
            for entry in trace.entries
            for reference in entry.exposed_references
        }

    def _was_exposed(
        self,
        reference: ReplyDraftGroundingReference,
        exposed: set[tuple[ReplyDrafterToolName, ReplyDraftGroundingReferenceType, UUID]],
    ) -> bool:
        if reference.reference_type is ReplyDraftGroundingReferenceType.CORRESPONDENCE:
            return any(
                record_type is reference.reference_type and record_id == reference.record_id
                for _, record_type, record_id in exposed
            )
        required_tool = self._REQUIRED_TOOL[reference.reference_type]
        return (required_tool, reference.reference_type, reference.record_id) in exposed

    @staticmethod
    def _validate_scope_reference(
        reference: ReplyDraftGroundingReference,
        scope: FollowUpReplyScope,
    ) -> None:
        expected = {
            ReplyDraftGroundingReferenceType.FOLLOW_UP: scope.follow_up_id,
            ReplyDraftGroundingReferenceType.PROJECT: scope.project_id,
            ReplyDraftGroundingReferenceType.REQUIREMENT: scope.requirement_id,
        }.get(reference.reference_type)
        if expected is not None and reference.record_id != expected:
            raise ReplyDraftGroundingValidationError(
                "grounding reference does not match the scoped authoritative record"
            )

    def _validate_evidence(
        self,
        evidence_ids: tuple[UUID, ...],
        scope: FollowUpReplyScope,
    ) -> None:
        rows = self.lineage.list_evidence_by_ids(set(evidence_ids))
        evidence_by_id = {item.id: item for item in rows}
        for evidence_id in evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if (
                item is None
                or item.validity is not EvidenceValidity.VALID
                or item.project_id != scope.project_id
                or item.requirement_id != scope.requirement_id
            ):
                raise ReplyDraftGroundingValidationError(
                    "evidence grounding is not currently valid for the scoped requirement"
                )

    def _validate_correspondence(
        self,
        correspondence_event_id: UUID,
        scope: FollowUpReplyScope,
    ) -> None:
        if self.correspondence.get(correspondence_event_id) is None or self.project_links.get_approved_link(
            correspondence_event_id=correspondence_event_id,
            project_id=scope.project_id,
        ) is None:
            raise ReplyDraftGroundingValidationError(
                "correspondence grounding is outside the scoped project"
            )

    def _validate_document(self, document_id: UUID, scope: FollowUpReplyScope) -> None:
        document = self.documents.get(document_id)
        if document is None or document.project_id != scope.project_id:
            raise ReplyDraftGroundingValidationError(
                "document grounding is outside the scoped project"
            )


class ReplyDraftGenerationService:
    """Creates one grounded GENERATED draft; external model work is outside DB writes."""

    def __init__(
        self,
        *,
        session: Session,
        eligibility_service: ReplyDraftEligibilityService,
        scoped_context_service: ScopedReplyDraftContextService,
        runner: ReplyDrafterRunner,
        grounding_validator: ReplyDraftGroundingValidator,
        follow_up_repository: FollowUpRepository,
        requirement_repository: RequirementRepository,
        reply_draft_repository: ReplyDraftRepository,
        lineage_repository: LineageRepository,
        project_contact_repository: ProjectContactRepository,
    ) -> None:
        self.session = session
        self.eligibility = eligibility_service
        self.contexts = scoped_context_service
        self.runner = runner
        self.grounding = grounding_validator
        self.follow_ups = follow_up_repository
        self.requirements = requirement_repository
        self.reply_drafts = reply_draft_repository
        self.lineage = lineage_repository
        self.contacts = project_contact_repository
        repositories = (
            follow_up_repository,
            requirement_repository,
            reply_draft_repository,
            lineage_repository,
            project_contact_repository,
        )
        if any(repository.session is not session for repository in repositories):
            raise ValueError("reply-draft generation repositories must share one session")

    async def generate(self, follow_up_id: UUID) -> ReplyDraftGenerationResult:
        existing = self.reply_drafts.find_active_for_follow_up(follow_up_id)
        if existing is not None:
            return self._existing_result(existing.id)

        scope = self._draftable_scope(follow_up_id)
        context = self.contexts.open(follow_up_id)
        # Release any read transaction before model/tool I/O.
        self.session.rollback()
        run = await self.runner.run(context)
        self.grounding.validate(
            proposal=run.proposal,
            trace=run.trace,
            scope=scope,
        )
        try:
            result = self._persist(
                follow_up_id=follow_up_id,
                original_scope=scope,
                proposal=run.proposal,
                trace=run.trace,
                model_identifier=run.model_identifier,
                prompt_version=run.prompt_version,
            )
            self.session.commit()
            return result
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.reply_drafts.find_active_for_follow_up(follow_up_id)
            if self._is_active_draft_integrity_error(exc) and existing is not None:
                return self._existing_result(existing.id)
            raise
        except Exception:
            self.session.rollback()
            raise

    def _persist(
        self,
        *,
        follow_up_id: UUID,
        original_scope: FollowUpReplyScope,
        proposal: ReplyDraftProposal,
        trace: ReplyDrafterRunTrace,
        model_identifier: str,
        prompt_version: str,
    ) -> ReplyDraftGenerationResult:
        follow_up = self.follow_ups.get_for_update(follow_up_id)
        if follow_up is None:
            raise ReplyDraftGenerationStaleScopeError("follow-up disappeared during generation")
        existing = self.reply_drafts.find_active_for_follow_up(follow_up_id, for_update=True)
        if existing is not None:
            return self._existing_result(existing.id)

        fresh_scope = self._draftable_scope(follow_up_id)
        if fresh_scope != original_scope:
            raise ReplyDraftGenerationStaleScopeError(
                "authoritative reply scope changed during generation"
            )
        requirement = self.requirements.get_for_update(fresh_scope.requirement_id)
        if (
            requirement is None
            or follow_up.project_id != fresh_scope.project_id
            or follow_up.requirement_id != fresh_scope.requirement_id
            or requirement.project_id != fresh_scope.project_id
        ):
            raise ReplyDraftGenerationStaleScopeError("authoritative lineage changed during generation")
        contact = self.contacts.get(fresh_scope.trusted_contact_id)
        if (
            contact is None
            or contact.project_id != fresh_scope.project_id
            or not contact.is_active
        ):
            raise ReplyDraftGenerationStaleScopeError("trusted contact changed during generation")
        # Recheck evidence against the final authoritative scope immediately before writes.
        evidence_ids = self.grounding.validate(
            proposal=proposal,
            trace=trace,
            scope=fresh_scope,
        )

        metadata = self._metadata(
            scope=fresh_scope,
            trace=trace,
            model_identifier=model_identifier,
            prompt_version=prompt_version,
        )
        persisted_proposal = self.lineage.create_proposal(
            correspondence_event_id=fresh_scope.source_correspondence_event_id,
            proposal_type=ProposalType.REPLY_DRAFT,
            model_identifier=model_identifier,
            prompt_version=prompt_version,
            input_hash=self._canonical_hash(metadata),
            input_metadata=metadata,
            structured_output=proposal.model_dump(mode="json"),
            evidence_item_ids=evidence_ids,
        )
        draft = self.reply_drafts.create_generated(
            follow_up_id=fresh_scope.follow_up_id,
            project_id=fresh_scope.project_id,
            requirement_id=fresh_scope.requirement_id,
            reply_type=proposal.reply_type,
            generated_subject=proposal.subject,
            generated_body=proposal.body,
            ai_proposal_id=persisted_proposal.id,
            source_correspondence_event_id=fresh_scope.source_correspondence_event_id,
            target_correspondence_event_id=fresh_scope.source_correspondence_event_id,
            project_contact_id=fresh_scope.trusted_contact_id,
            recipient_email=contact.email_normalized,
            gmail_thread_id=fresh_scope.gmail_thread_id,
            source_gmail_message_id=fresh_scope.gmail_message_id,
        )
        self.lineage.create_audit_event(
            event_type=REPLY_DRAFT_GENERATED_AUDIT_EVENT,
            actor_type="system",
            correspondence_event_id=fresh_scope.source_correspondence_event_id,
            project_id=fresh_scope.project_id,
            requirement_id=fresh_scope.requirement_id,
            ai_proposal_id=persisted_proposal.id,
            details={
                "follow_up_id": str(fresh_scope.follow_up_id),
                "reply_draft_id": str(draft.id),
                "source_correspondence_event_id": str(
                    fresh_scope.source_correspondence_event_id
                ),
                "model_identifier": model_identifier,
                "prompt_version": prompt_version,
            },
        )
        return ReplyDraftGenerationResult(
            status=ReplyDraftGenerationStatus.GENERATED_NEW,
            reply_draft_id=draft.id,
            ai_proposal_id=persisted_proposal.id,
        )

    def _draftable_scope(self, follow_up_id: UUID) -> FollowUpReplyScope:
        eligibility = self.eligibility.assess(follow_up_id)
        if (
            eligibility.status is not ReplyDraftEligibilityStatus.DRAFTABLE
            or eligibility.scope is None
        ):
            raise ReplyDraftGenerationNotDraftableError(eligibility)
        return eligibility.scope

    @staticmethod
    def _existing_result(reply_draft_id: UUID) -> ReplyDraftGenerationResult:
        return ReplyDraftGenerationResult(
            status=ReplyDraftGenerationStatus.EXISTING_ACTIVE_DRAFT,
            reply_draft_id=reply_draft_id,
        )

    @staticmethod
    def _metadata(
        *,
        scope: FollowUpReplyScope,
        trace: ReplyDrafterRunTrace,
        model_identifier: str,
        prompt_version: str,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "follow_up_scope": scope.model_dump(mode="json"),
            "model_identifier": model_identifier,
            "prompt_version": prompt_version,
            "successful_tool_trace": trace.model_dump(mode="json"),
        }

    @staticmethod
    def _canonical_hash(payload: dict[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _is_active_draft_integrity_error(exc: IntegrityError) -> bool:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        return constraint == "uq_reply_drafts_active_follow_up"
