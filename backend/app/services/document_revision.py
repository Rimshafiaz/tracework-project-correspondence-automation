from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.document_revision import (
    DOCUMENT_REVISION_POLICY_VERSION,
    DocumentRevisionDecision,
    DocumentRevisionEffect,
    DocumentRevisionParseResult,
    DocumentRevisionRule,
    RevisionOutcome,
    RevisionParseStatus,
)
from app.models.document import Document
from app.models.enums import (
    DocumentRevisionStatus,
    ReviewType,
    TransitionDisposition,
    TransitionStatus,
)
from app.normalization.document_revision import parse_document_revision
from app.repositories.document import DocumentRepository
from app.repositories.lineage import LineageRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.policy.document_revision_rules import (
    reason_for_document_revision_rule,
)


DOCUMENT_REVISION_ENTITY_TYPE = "document_revision"
DOCUMENT_REVISION_SELECTED_CURRENT = "document_revision_selected_current"
DOCUMENT_REVISION_RETAINED_HISTORICAL = "document_revision_retained_historical"
DOCUMENT_REVISION_DUPLICATE_RECORDED = "document_revision_duplicate_recorded"
DOCUMENT_REVISION_REVIEW_CREATED = "document_revision_review_created"


class DocumentRevisionIntegrityError(RuntimeError):
    pass


class DocumentRevisionService:
    """Applies deterministic revision policy to one already-filed document."""

    def __init__(
        self,
        *,
        session: Session,
        document_repository: DocumentRepository,
        lineage_repository: LineageRepository,
        review_repository: ReviewItemRepository,
    ) -> None:
        self.session = session
        self.document_repository = document_repository
        self.lineage_repository = lineage_repository
        self.review_repository = review_repository

    def evaluate_filed_document(
        self,
        *,
        document_id: UUID,
        correspondence_event_id: UUID,
        ai_proposal_id: UUID,
        policy_evaluation_id: UUID,
    ) -> DocumentRevisionDecision:
        incoming = self.document_repository.get_for_update(document_id)
        if incoming is None:
            raise DocumentRevisionIntegrityError("filed document was not found")

        existing_transition = self.lineage_repository.get_state_transition_for_update(
            policy_evaluation_id=policy_evaluation_id,
            affected_entity_type=DOCUMENT_REVISION_ENTITY_TYPE,
            affected_entity_id=incoming.id,
        )
        if incoming.revision_status is not DocumentRevisionStatus.UNASSESSED:
            if existing_transition is None:
                raise DocumentRevisionIntegrityError(
                    "assessed document is missing its revision transition"
                )
            return self._persisted_decision(incoming, existing_transition)

        parsed = parse_document_revision(incoming.filename)
        now = datetime.now(UTC)
        members: tuple[Document, ...] = ()
        current: Document | None = None
        blocked_family = False

        if parsed.status is RevisionParseStatus.PARSED:
            members = tuple(
                item
                for item in self.document_repository.list_family_members(
                    project_id=incoming.project_id,
                    category=incoming.category,
                    document_family_key=parsed.family_key,
                    for_update=True,
                )
                if item.id != incoming.id
            )
            current_members = tuple(
                item
                for item in members
                if item.revision_status is DocumentRevisionStatus.CURRENT
            )
            current = current_members[0] if len(current_members) == 1 else None
            blocked_family = (
                len(current_members) > 1
                or any(
                    item.revision_status
                    in {
                        DocumentRevisionStatus.REVIEW_REQUIRED,
                        DocumentRevisionStatus.UNASSESSED,
                    }
                    for item in members
                )
                or self._has_matching_legacy_unassessed(incoming, parsed)
                or (bool(members) and current is None)
            )

        outcome, rules, old_current_outcome = self._decide(
            incoming=incoming,
            parsed=parsed,
            members=members,
            current=current,
            blocked_family=blocked_family,
        )
        reasons = tuple(reason_for_document_revision_rule(rule) for rule in rules)
        effect = DocumentRevisionEffect(
            document_id=incoming.id,
            source_attachment_id=incoming.source_attachment_id,
            project_id=incoming.project_id,
            category=incoming.category,
            family_key=parsed.family_key,
            raw_revision_label=parsed.raw_revision,
            normalized_revision=parsed.normalized_revision,
            revision_order=parsed.revision_order,
            previous_current_document_id=current.id if current is not None else None,
            previous_current_revision=(
                current.revision_normalized if current is not None else None
            ),
            incoming_outcome=outcome,
            old_current_outcome=old_current_outcome,
            policy_version=DOCUMENT_REVISION_POLICY_VERSION,
            triggered_rule_ids=rules,
            reasons=reasons,
        )
        current_state = self._current_state(parsed, current, members)
        proposed_state = self._proposed_state(effect)
        evidence = self.lineage_repository.list_policy_evidence(policy_evaluation_id)
        transition = existing_transition or self.lineage_repository.create_transition(
            ai_proposal_id=ai_proposal_id,
            policy_evaluation_id=policy_evaluation_id,
            affected_entity_type=DOCUMENT_REVISION_ENTITY_TYPE,
            affected_entity_id=incoming.id,
            current_state=current_state,
            proposed_state=proposed_state,
            requirement_effects=[],
            document_effects=[effect.model_dump(mode="json")],
            follow_up_effects=[],
            disposition=(
                TransitionDisposition.REVIEW
                if outcome is RevisionOutcome.REVIEW_REQUIRED
                else TransitionDisposition.AUTO_APPLY
            ),
            evidence_item_ids=tuple(item.id for item in evidence),
        )

        self._apply_metadata(
            incoming=incoming,
            current=current,
            parsed=parsed,
            outcome=outcome,
            old_current_outcome=old_current_outcome,
            decided_at=now,
        )
        review = None
        if outcome is RevisionOutcome.REVIEW_REQUIRED:
            review = self.review_repository.get_by_state_transition(transition.id)
            if review is None:
                review = self.lineage_repository.create_review_item(
                    correspondence_event_id=correspondence_event_id,
                    state_transition_id=transition.id,
                    review_type=ReviewType.DOCUMENT_REVISION,
                    review_reason=" ".join(reasons),
                )
        elif transition.status is TransitionStatus.PREVIEWED:
            self.lineage_repository.mark_transition_applied(
                transition,
                applied_at=now,
            )

        event_type = self._event_type(outcome)
        if self.lineage_repository.get_audit_event_for_transition(
            event_type=event_type,
            state_transition_id=transition.id,
        ) is None:
            self.lineage_repository.create_audit_event(
                event_type=event_type,
                actor_type="system",
                correspondence_event_id=correspondence_event_id,
                project_id=incoming.project_id,
                ai_proposal_id=ai_proposal_id,
                policy_evaluation_id=policy_evaluation_id,
                state_transition_id=transition.id,
                review_item_id=review.id if review is not None else None,
                details={
                    "document_id": str(incoming.id),
                    "source_attachment_id": str(incoming.source_attachment_id),
                    "family_key": parsed.family_key,
                    "revision_label": parsed.raw_revision,
                    "revision_normalized": parsed.normalized_revision,
                    "previous_current_document_id": (
                        str(current.id) if current is not None else None
                    ),
                    "policy_version": DOCUMENT_REVISION_POLICY_VERSION,
                    "triggered_rule_ids": [rule.value for rule in rules],
                    "outcome": outcome.value,
                },
            )
        return DocumentRevisionDecision(
            document_id=incoming.id,
            state_transition_id=transition.id,
            review_item_id=review.id if review is not None else None,
            outcome=outcome,
            policy_version=DOCUMENT_REVISION_POLICY_VERSION,
            triggered_rule_ids=rules,
        )

    def _has_matching_legacy_unassessed(
        self,
        incoming: Document,
        parsed: DocumentRevisionParseResult,
    ) -> bool:
        for item in self.document_repository.list_unassessed_for_project_category(
            project_id=incoming.project_id,
            category=incoming.category,
            for_update=True,
        ):
            if item.id == incoming.id:
                continue
            item_parse = parse_document_revision(item.filename)
            if (
                item_parse.status is RevisionParseStatus.PARSED
                and item_parse.family_key == parsed.family_key
            ):
                return True
        return False

    @staticmethod
    def _decide(
        *,
        incoming: Document,
        parsed: DocumentRevisionParseResult,
        members: tuple[Document, ...],
        current: Document | None,
        blocked_family: bool,
    ) -> tuple[
        RevisionOutcome,
        tuple[DocumentRevisionRule, ...],
        RevisionOutcome | None,
    ]:
        if parsed.status is RevisionParseStatus.NO_REVISION:
            return (
                RevisionOutcome.REVIEW_REQUIRED,
                (DocumentRevisionRule.MISSING_REVISION_REVIEW,),
                None,
            )
        if parsed.status is RevisionParseStatus.UNSUPPORTED:
            return (
                RevisionOutcome.REVIEW_REQUIRED,
                (DocumentRevisionRule.UNSUPPORTED_REVISION_REVIEW,),
                None,
            )
        if blocked_family:
            return (
                RevisionOutcome.REVIEW_REQUIRED,
                (
                    DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
                    DocumentRevisionRule.FAMILY_UNASSESSED_REVIEW,
                ),
                None,
            )

        same_revision = tuple(
            item
            for item in members
            if item.revision_normalized == parsed.normalized_revision
        )
        if any(item.content_hash != incoming.content_hash for item in same_revision):
            return (
                RevisionOutcome.REVIEW_REQUIRED,
                (
                    DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
                    DocumentRevisionRule.SAME_REVISION_DIFFERENT_CONTENT_REVIEW,
                ),
                None,
            )
        if same_revision:
            return (
                RevisionOutcome.DUPLICATE,
                (
                    DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
                    DocumentRevisionRule.SAME_REVISION_SAME_CONTENT_DUPLICATE,
                ),
                None,
            )
        if current is None:
            return (
                RevisionOutcome.CURRENT,
                (
                    DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
                    DocumentRevisionRule.FIRST_REVISION_CURRENT,
                ),
                None,
            )
        if parsed.revision_order > current.revision_order:
            return (
                RevisionOutcome.CURRENT,
                (
                    DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
                    DocumentRevisionRule.NEWER_REVISION_CURRENT,
                ),
                RevisionOutcome.HISTORICAL,
            )
        return (
            RevisionOutcome.HISTORICAL,
            (
                DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
                DocumentRevisionRule.OLDER_REVISION_HISTORICAL,
            ),
            None,
        )

    def _apply_metadata(
        self,
        *,
        incoming: Document,
        current: Document | None,
        parsed: DocumentRevisionParseResult,
        outcome: RevisionOutcome,
        old_current_outcome: RevisionOutcome | None,
        decided_at: datetime,
    ) -> None:
        if old_current_outcome is RevisionOutcome.HISTORICAL and current is not None:
            self.document_repository.update_revision_metadata(
                current,
                document_family_key=current.document_family_key,
                revision_label=current.revision_label,
                revision_normalized=current.revision_normalized,
                revision_order=current.revision_order,
                revision_status=DocumentRevisionStatus.HISTORICAL,
                revision_decided_at=decided_at,
            )
        self.document_repository.update_revision_metadata(
            incoming,
            document_family_key=parsed.family_key,
            revision_label=parsed.raw_revision,
            revision_normalized=parsed.normalized_revision,
            revision_order=parsed.revision_order,
            revision_status=DocumentRevisionStatus(outcome.value),
            revision_decided_at=decided_at,
        )

    @staticmethod
    def _current_state(
        parsed: DocumentRevisionParseResult,
        current: Document | None,
        members: tuple[Document, ...],
    ) -> dict[str, object]:
        return {
            "family_key": parsed.family_key,
            "current_document_id": str(current.id) if current is not None else None,
            "current_revision": (
                current.revision_normalized if current is not None else None
            ),
            "family_members": [
                {
                    "document_id": str(item.id),
                    "revision_status": item.revision_status.value,
                    "revision_normalized": item.revision_normalized,
                    "content_hash": item.content_hash,
                }
                for item in members
            ],
        }

    @staticmethod
    def _proposed_state(effect: DocumentRevisionEffect) -> dict[str, object]:
        return {
            "family_key": effect.family_key,
            "incoming_document_id": str(effect.document_id),
            "incoming_outcome": effect.incoming_outcome.value,
            "previous_current_document_id": (
                str(effect.previous_current_document_id)
                if effect.previous_current_document_id is not None
                else None
            ),
            "old_current_outcome": (
                effect.old_current_outcome.value
                if effect.old_current_outcome is not None
                else None
            ),
        }

    @staticmethod
    def _event_type(outcome: RevisionOutcome) -> str:
        return {
            RevisionOutcome.CURRENT: DOCUMENT_REVISION_SELECTED_CURRENT,
            RevisionOutcome.HISTORICAL: DOCUMENT_REVISION_RETAINED_HISTORICAL,
            RevisionOutcome.DUPLICATE: DOCUMENT_REVISION_DUPLICATE_RECORDED,
            RevisionOutcome.REVIEW_REQUIRED: DOCUMENT_REVISION_REVIEW_CREATED,
        }[outcome]

    def _persisted_decision(self, incoming, transition) -> DocumentRevisionDecision:
        try:
            outcome = RevisionOutcome(incoming.revision_status.value)
            effect = DocumentRevisionEffect.model_validate(
                transition.document_effects[0]
            )
        except (ValueError, IndexError) as exc:
            raise DocumentRevisionIntegrityError(
                "persisted revision decision is invalid"
            ) from exc
        review = self.review_repository.get_by_state_transition(transition.id)
        return DocumentRevisionDecision(
            document_id=incoming.id,
            state_transition_id=transition.id,
            review_item_id=review.id if review is not None else None,
            outcome=outcome,
            policy_version=effect.policy_version,
            triggered_rule_ids=effect.triggered_rule_ids,
        )
