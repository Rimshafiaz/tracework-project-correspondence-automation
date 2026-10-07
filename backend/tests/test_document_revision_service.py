from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.contracts.document_revision import (
    DOCUMENT_REVISION_POLICY_VERSION,
    DocumentRevisionEffect,
    DocumentRevisionRule,
    RevisionOutcome,
)
from app.models.document import Document
from app.models.enums import (
    DocumentFilingStatus,
    DocumentRevisionStatus,
    ReviewType,
    TransitionDisposition,
    TransitionStatus,
)
from app.services.document_revision import (
    DOCUMENT_REVISION_DUPLICATE_RECORDED,
    DOCUMENT_REVISION_ENTITY_TYPE,
    DOCUMENT_REVISION_REVIEW_CREATED,
    DOCUMENT_REVISION_RETAINED_HISTORICAL,
    DOCUMENT_REVISION_SELECTED_CURRENT,
    DocumentRevisionService,
)


PROJECT_ID = uuid4()
EVENT_ID = uuid4()
PROPOSAL_ID = uuid4()
EVALUATION_ID = uuid4()


def _document(
    filename: str,
    *,
    content_hash: str = "a" * 64,
    status: DocumentRevisionStatus = DocumentRevisionStatus.UNASSESSED,
    family: str | None = None,
    normalized: str | None = None,
    order: int | None = None,
) -> Document:
    return Document(
        id=uuid4(),
        project_id=PROJECT_ID,
        source_attachment_id=uuid4(),
        filename=filename,
        category="Documents",
        content_hash=content_hash,
        filing_status=DocumentFilingStatus.FILED,
        revision_status=status,
        document_family_key=family,
        revision_label=normalized,
        revision_normalized=normalized,
        revision_order=order,
    )


class _Documents:
    def __init__(self, incoming: Document, members: tuple[Document, ...] = ()) -> None:
        self.incoming = incoming
        self.members = members
        self.updates = []

    def get_for_update(self, document_id):
        return self.incoming if document_id == self.incoming.id else None

    def list_family_members(self, **kwargs):
        return tuple(
            item
            for item in self.members
            if item.project_id == kwargs["project_id"]
            and item.category == kwargs["category"]
            and item.document_family_key == kwargs["document_family_key"]
        )

    def list_unassessed_for_project_category(self, **kwargs):
        return tuple(
            item
            for item in (self.incoming, *self.members)
            if item.project_id == kwargs["project_id"]
            and item.category == kwargs["category"]
            and item.revision_status is DocumentRevisionStatus.UNASSESSED
        )

    def update_revision_metadata(self, document, **values):
        for name, value in values.items():
            setattr(document, name, value)
        self.updates.append((document.id, values.copy()))
        return document


def _fixture(incoming: Document, members: tuple[Document, ...] = ()):
    documents = _Documents(incoming, members)
    lineage = MagicMock()
    reviews = MagicMock()
    reviews.get_by_state_transition.return_value = None
    transition = SimpleNamespace(
        id=uuid4(),
        status=TransitionStatus.PREVIEWED,
        document_effects=[],
    )
    review = SimpleNamespace(id=uuid4())
    lineage.get_state_transition_for_update.return_value = None
    lineage.list_policy_evidence.return_value = ()
    lineage.create_transition.return_value = transition
    lineage.create_review_item.return_value = review
    lineage.get_audit_event_for_transition.return_value = None

    def create_transition(**values):
        transition.document_effects = values["document_effects"]
        transition.current_state = values["current_state"]
        transition.proposed_state = values["proposed_state"]
        transition.disposition = values["disposition"]
        return transition

    def mark_applied(item, *, applied_at):
        item.status = TransitionStatus.APPLIED
        item.applied_at = applied_at
        return item

    lineage.create_transition.side_effect = create_transition
    lineage.mark_transition_applied.side_effect = mark_applied
    service = DocumentRevisionService(
        session=MagicMock(),
        document_repository=documents,
        lineage_repository=lineage,
        review_repository=reviews,
    )
    return SimpleNamespace(**locals())


def _evaluate(deps):
    return deps.service.evaluate_filed_document(
        document_id=deps.incoming.id,
        correspondence_event_id=EVENT_ID,
        ai_proposal_id=PROPOSAL_ID,
        policy_evaluation_id=EVALUATION_ID,
    )


def test_first_parsed_revision_becomes_current_with_frozen_transition_and_audit():
    deps = _fixture(_document("Structural Plan Rev 1.pdf"))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.CURRENT
    assert deps.incoming.revision_status is DocumentRevisionStatus.CURRENT
    assert deps.incoming.document_family_key == "structural plan"
    assert deps.transition.status is TransitionStatus.APPLIED
    assert deps.transition.disposition is TransitionDisposition.AUTO_APPLY
    assert deps.transition.current_state["current_document_id"] is None
    assert deps.transition.proposed_state["incoming_outcome"] == "CURRENT"
    effect = DocumentRevisionEffect.model_validate(deps.transition.document_effects[0])
    assert effect.policy_version == DOCUMENT_REVISION_POLICY_VERSION
    assert effect.triggered_rule_ids == (
        DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION,
        DocumentRevisionRule.FIRST_REVISION_CURRENT,
    )
    transition_call = deps.lineage.create_transition.call_args.kwargs
    assert transition_call["ai_proposal_id"] == PROPOSAL_ID
    assert transition_call["policy_evaluation_id"] == EVALUATION_ID
    assert transition_call["affected_entity_type"] == DOCUMENT_REVISION_ENTITY_TYPE
    assert deps.lineage.create_audit_event.call_args.kwargs["event_type"] == (
        DOCUMENT_REVISION_SELECTED_CURRENT
    )


def test_newer_revision_replaces_current_atomically():
    current = _document(
        "Structural Plan Rev 3.pdf",
        status=DocumentRevisionStatus.CURRENT,
        family="structural plan",
        normalized="REV-3",
        order=3,
    )
    incoming = _document("Structural Plan Rev 4.pdf")
    deps = _fixture(incoming, (current,))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.CURRENT
    assert current.revision_status is DocumentRevisionStatus.HISTORICAL
    assert incoming.revision_status is DocumentRevisionStatus.CURRENT
    effect = DocumentRevisionEffect.model_validate(deps.transition.document_effects[0])
    assert effect.previous_current_document_id == current.id
    assert effect.old_current_outcome is RevisionOutcome.HISTORICAL


def test_older_revision_is_historical_and_current_is_unchanged():
    current = _document(
        "Structural Plan Rev 4.pdf",
        status=DocumentRevisionStatus.CURRENT,
        family="structural plan",
        normalized="REV-4",
        order=4,
    )
    incoming = _document("Structural Plan Rev 3.pdf")
    deps = _fixture(incoming, (current,))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.HISTORICAL
    assert current.revision_status is DocumentRevisionStatus.CURRENT
    assert incoming.revision_status is DocumentRevisionStatus.HISTORICAL
    assert deps.lineage.create_audit_event.call_args.kwargs["event_type"] == (
        DOCUMENT_REVISION_RETAINED_HISTORICAL
    )


def test_same_revision_and_hash_is_retained_as_duplicate():
    current = _document(
        "Structural Plan Rev 4.pdf",
        status=DocumentRevisionStatus.CURRENT,
        family="structural plan",
        normalized="REV-4",
        order=4,
    )
    incoming = _document("Structural Plan R4.pdf")
    current.drive_file_id = "drive-current"
    incoming.drive_file_id = "drive-duplicate"
    deps = _fixture(incoming, (current,))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.DUPLICATE
    assert incoming.revision_status is DocumentRevisionStatus.DUPLICATE
    assert current.revision_status is DocumentRevisionStatus.CURRENT
    assert current.drive_file_id == "drive-current"
    assert incoming.drive_file_id == "drive-duplicate"
    assert deps.lineage.create_audit_event.call_args.kwargs["event_type"] == (
        DOCUMENT_REVISION_DUPLICATE_RECORDED
    )


@pytest.mark.parametrize(
    "filename",
    ["Structural Plan Rev A.pdf", "Structural Plan.pdf"],
)
def test_unsupported_or_missing_revision_requires_inspection(filename):
    incoming = _document(filename)
    deps = _fixture(incoming)

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.REVIEW_REQUIRED
    assert incoming.revision_status is DocumentRevisionStatus.REVIEW_REQUIRED
    assert deps.transition.status is TransitionStatus.PREVIEWED
    assert deps.transition.disposition is TransitionDisposition.REVIEW
    assert deps.lineage.create_review_item.call_args.kwargs["review_type"] is (
        ReviewType.DOCUMENT_REVISION
    )
    assert deps.lineage.create_audit_event.call_args.kwargs["event_type"] == (
        DOCUMENT_REVISION_REVIEW_CREATED
    )


def test_same_revision_with_different_content_requires_review():
    current = _document(
        "Structural Plan Rev 4.pdf",
        content_hash="a" * 64,
        status=DocumentRevisionStatus.CURRENT,
        family="structural plan",
        normalized="REV-4",
        order=4,
    )
    incoming = _document("Structural Plan R4.pdf", content_hash="b" * 64)
    deps = _fixture(incoming, (current,))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.REVIEW_REQUIRED
    assert current.revision_status is DocumentRevisionStatus.CURRENT
    assert incoming.revision_status is DocumentRevisionStatus.REVIEW_REQUIRED
    effect = DocumentRevisionEffect.model_validate(deps.transition.document_effects[0])
    assert DocumentRevisionRule.SAME_REVISION_DIFFERENT_CONTENT_REVIEW in (
        effect.triggered_rule_ids
    )


@pytest.mark.parametrize("blocking_status", [DocumentRevisionStatus.REVIEW_REQUIRED, DocumentRevisionStatus.UNASSESSED])
def test_unresolved_or_legacy_family_state_blocks_automatic_replacement(blocking_status):
    blocker = _document(
        "Structural Plan Rev 2.pdf",
        status=blocking_status,
        family=("structural plan" if blocking_status is not DocumentRevisionStatus.UNASSESSED else None),
        normalized=("REV-2" if blocking_status is not DocumentRevisionStatus.UNASSESSED else None),
        order=(2 if blocking_status is not DocumentRevisionStatus.UNASSESSED else None),
    )
    incoming = _document("Structural Plan Rev 5.pdf")
    deps = _fixture(incoming, (blocker,))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.REVIEW_REQUIRED
    effect = DocumentRevisionEffect.model_validate(deps.transition.document_effects[0])
    assert DocumentRevisionRule.FAMILY_UNASSESSED_REVIEW in effect.triggered_rule_ids


def test_separate_families_are_evaluated_independently():
    other = _document(
        "Fire Plan Rev 9.pdf",
        status=DocumentRevisionStatus.REVIEW_REQUIRED,
        family="fire plan",
        normalized="REV-9",
        order=9,
    )
    incoming = _document("Structural Plan Rev 1.pdf")
    deps = _fixture(incoming, (other,))

    result = _evaluate(deps)

    assert result.outcome is RevisionOutcome.CURRENT
    assert other.revision_status is DocumentRevisionStatus.REVIEW_REQUIRED


def test_retry_reuses_persisted_transition_review_and_audit_decision():
    incoming = _document("Structural Plan Rev A.pdf")
    deps = _fixture(incoming)
    first = _evaluate(deps)
    update_count = len(deps.documents.updates)
    deps.lineage.get_state_transition_for_update.return_value = deps.transition
    deps.reviews.get_by_state_transition.return_value = deps.review

    second = _evaluate(deps)

    assert second == first
    assert len(deps.documents.updates) == update_count
    deps.lineage.create_transition.assert_called_once()
    deps.lineage.create_review_item.assert_called_once()
    deps.lineage.create_audit_event.assert_called_once()


def test_retry_of_automatic_decision_is_a_no_op():
    incoming = _document("Structural Plan Rev 1.pdf")
    deps = _fixture(incoming)
    first = _evaluate(deps)
    update_count = len(deps.documents.updates)
    deps.lineage.get_state_transition_for_update.return_value = deps.transition

    second = _evaluate(deps)

    assert second == first
    assert len(deps.documents.updates) == update_count
    deps.lineage.create_transition.assert_called_once()
    deps.lineage.create_audit_event.assert_called_once()
    deps.lineage.mark_transition_applied.assert_called_once()
