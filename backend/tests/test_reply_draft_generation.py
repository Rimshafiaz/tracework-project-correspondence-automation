import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.reply_drafter_context import (
    ReplyDrafterRunTrace,
    ReplyDrafterToolName,
    ReplyDrafterToolTraceEntry,
)
from app.ai.reply_drafter_schemas import (
    ReplyDraftGroundingReference,
    ReplyDraftGroundingReferenceType as RefType,
    ReplyDraftProposal,
)
from app.contracts.reply_draft_context import FollowUpReplyScope, ReplyDraftEligibility, ReplyDraftEligibilityStatus
from app.models.enums import EvidenceValidity, ReplyDraftStatus, ReplyType
from app.models.enums import ProposalType
from app.services.reply_draft_generation import (
    ReplyDraftGenerationNotDraftableError,
    ReplyDraftGenerationService,
    ReplyDraftGenerationStaleScopeError,
    ReplyDraftGroundingValidationError,
    ReplyDraftGroundingValidator,
)
from app.services.reply_drafter_runner import ReplyDrafterRunResult


def _scope():
    return FollowUpReplyScope(
        follow_up_id=uuid4(),
        project_id=uuid4(),
        requirement_id=uuid4(),
        source_correspondence_event_id=uuid4(),
        trusted_contact_id=uuid4(),
        gmail_message_id="gmail-message",
        gmail_thread_id="gmail-thread",
        originating_state_transition_id=uuid4(),
    )


def _trace(scope, evidence_id=None, correspondence_id=None, document_id=None):
    evidence_id = evidence_id or uuid4()
    correspondence_id = correspondence_id or scope.source_correspondence_event_id
    document_id = document_id or uuid4()
    entries = (
        (ReplyDrafterToolName.GET_DUE_FOLLOW_UP, ((RefType.FOLLOW_UP, scope.follow_up_id),)),
        (ReplyDrafterToolName.GET_PROJECT_SUMMARY, ((RefType.PROJECT, scope.project_id),)),
        (ReplyDrafterToolName.GET_REQUIREMENT_CONTEXT, ((RefType.REQUIREMENT, scope.requirement_id), (RefType.EVIDENCE, evidence_id), (RefType.CORRESPONDENCE, correspondence_id))),
        (ReplyDrafterToolName.LIST_DOCUMENT_REVISION_STATUS, ((RefType.DOCUMENT, document_id),)),
    )
    return ReplyDrafterRunTrace(
        follow_up_id=scope.follow_up_id,
        entries=tuple(
            ReplyDrafterToolTraceEntry(
                tool_name=tool_name,
                result={},
                exposed_references=tuple(
                    ReplyDraftGroundingReference(reference_type=kind, record_id=record_id)
                    for kind, record_id in references
                ),
            )
            for tool_name, references in entries
        ),
    ), evidence_id, correspondence_id, document_id


def _proposal(*references):
    return ReplyDraftProposal(
        reply_type=ReplyType.OVERDUE_FOLLOW_UP,
        subject="Schedule follow-up",
        body="Please provide the outstanding schedule.",
        grounding_references=references,
    )


def _validator(*, evidence=None, correspondence=None, document=None, link=True):
    lineage = MagicMock()
    lineage.list_evidence_by_ids.return_value = [] if evidence is None else [evidence]
    correspondences = MagicMock()
    correspondences.get.return_value = correspondence if correspondence is not None else SimpleNamespace()
    links = MagicMock()
    links.get_approved_link.return_value = SimpleNamespace() if link else None
    documents = MagicMock()
    documents.get.return_value = document
    return ReplyDraftGroundingValidator(
        lineage_repository=lineage,
        correspondence_repository=correspondences,
        project_link_repository=links,
        document_repository=documents,
    ), lineage, correspondences, links, documents


def test_grounding_validator_accepts_all_six_trace_exposed_categories():
    scope = _scope()
    trace, evidence_id, correspondence_id, document_id = _trace(scope)
    evidence = SimpleNamespace(
        id=evidence_id,
        validity=EvidenceValidity.VALID,
        project_id=scope.project_id,
        requirement_id=scope.requirement_id,
    )
    document = SimpleNamespace(id=document_id, project_id=scope.project_id)
    validator, *_ = _validator(evidence=evidence, document=document)
    proposal = _proposal(
        *(
            ReplyDraftGroundingReference(reference_type=kind, record_id=record_id)
            for kind, record_id in (
                (RefType.FOLLOW_UP, scope.follow_up_id),
                (RefType.PROJECT, scope.project_id),
                (RefType.REQUIREMENT, scope.requirement_id),
                (RefType.EVIDENCE, evidence_id),
                (RefType.CORRESPONDENCE, correspondence_id),
                (RefType.DOCUMENT, document_id),
            )
        )
    )

    assert validator.validate(proposal=proposal, trace=trace, scope=scope) == (evidence_id,)


@pytest.mark.parametrize("reference_type", tuple(RefType))
def test_grounding_validator_rejects_unseen_or_wrong_category_references(reference_type):
    scope = _scope()
    trace, evidence_id, _, _ = _trace(scope)
    validator, *_ = _validator(
        evidence=SimpleNamespace(
            id=evidence_id,
            validity=EvidenceValidity.VALID,
            project_id=scope.project_id,
            requirement_id=scope.requirement_id,
        )
    )
    with pytest.raises(ReplyDraftGroundingValidationError):
        validator.validate(
            proposal=_proposal(
                ReplyDraftGroundingReference(reference_type=reference_type, record_id=uuid4())
            ),
            trace=trace,
            scope=scope,
        )


def test_grounding_validator_rejects_invalid_evidence_and_cross_project_records():
    scope = _scope()
    trace, evidence_id, correspondence_id, document_id = _trace(scope)
    invalid_evidence = SimpleNamespace(
        id=evidence_id,
        validity=EvidenceValidity.INVALIDATED,
        project_id=scope.project_id,
        requirement_id=scope.requirement_id,
    )
    validator, *_ = _validator(
        evidence=invalid_evidence,
        document=SimpleNamespace(id=document_id, project_id=uuid4()),
    )
    with pytest.raises(ReplyDraftGroundingValidationError):
        validator.validate(
            proposal=_proposal(ReplyDraftGroundingReference(reference_type=RefType.EVIDENCE, record_id=evidence_id)),
            trace=trace,
            scope=scope,
        )

    valid_evidence = SimpleNamespace(
        id=evidence_id,
        validity=EvidenceValidity.VALID,
        project_id=scope.project_id,
        requirement_id=scope.requirement_id,
    )
    validator, *_ = _validator(
        evidence=valid_evidence,
        document=SimpleNamespace(id=document_id, project_id=uuid4()),
    )
    with pytest.raises(ReplyDraftGroundingValidationError):
        validator.validate(
            proposal=_proposal(ReplyDraftGroundingReference(reference_type=RefType.DOCUMENT, record_id=document_id)),
            trace=trace,
            scope=scope,
        )
    validator, _, _, _, _ = _validator(evidence=valid_evidence, link=False)
    with pytest.raises(ReplyDraftGroundingValidationError):
        validator.validate(
            proposal=_proposal(ReplyDraftGroundingReference(reference_type=RefType.CORRESPONDENCE, record_id=correspondence_id)),
            trace=trace,
            scope=scope,
        )


def test_grounding_validator_rejects_a_trace_for_another_follow_up():
    scope = _scope()
    trace, evidence_id, _, _ = _trace(scope)
    validator, *_ = _validator(
        evidence=SimpleNamespace(
            id=evidence_id,
            validity=EvidenceValidity.VALID,
            project_id=scope.project_id,
            requirement_id=scope.requirement_id,
        )
    )
    with pytest.raises(ReplyDraftGroundingValidationError, match="different follow-up"):
        validator.validate(
            proposal=_proposal(ReplyDraftGroundingReference(reference_type=RefType.EVIDENCE, record_id=evidence_id)),
            trace=trace.model_copy(update={"follow_up_id": uuid4()}),
            scope=scope,
        )


def test_grounding_validator_does_not_cross_authorize_categories_or_unshown_origin():
    scope = _scope()
    trace, evidence_id, _, _ = _trace(scope)
    valid_evidence = SimpleNamespace(
        id=evidence_id,
        validity=EvidenceValidity.VALID,
        project_id=scope.project_id,
        requirement_id=scope.requirement_id,
    )
    validator, *_ = _validator(evidence=valid_evidence)
    with pytest.raises(ReplyDraftGroundingValidationError):
        validator.validate(
            proposal=_proposal(
                ReplyDraftGroundingReference(reference_type=RefType.DOCUMENT, record_id=evidence_id)
            ),
            trace=trace,
            scope=scope,
        )

    trace_without_correspondence = ReplyDrafterRunTrace(
        follow_up_id=scope.follow_up_id,
        entries=tuple(
            entry.model_copy(
                update={
                    "exposed_references": tuple(
                        reference
                        for reference in entry.exposed_references
                        if reference.reference_type is not RefType.CORRESPONDENCE
                    )
                }
            )
            for entry in trace.entries
        ),
    )
    with pytest.raises(ReplyDraftGroundingValidationError):
        validator.validate(
            proposal=_proposal(
                ReplyDraftGroundingReference(
                    reference_type=RefType.CORRESPONDENCE,
                    record_id=scope.source_correspondence_event_id,
                )
            ),
            trace=trace_without_correspondence,
            scope=scope,
        )
def _generation_service(*, active_before=None, active_after=None, fresh_scope=None):
    scope = _scope()
    session = MagicMock(spec=Session)
    eligibility = MagicMock()
    eligibility.assess.side_effect = [
        ReplyDraftEligibility(status=ReplyDraftEligibilityStatus.DRAFTABLE, scope=scope),
        ReplyDraftEligibility(status=ReplyDraftEligibilityStatus.DRAFTABLE, scope=fresh_scope or scope),
    ]
    contexts = MagicMock()
    contexts.open.return_value = MagicMock()
    trace, evidence_id, _, _ = _trace(scope)
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=ReplyDrafterRunResult(
            proposal=_proposal(ReplyDraftGroundingReference(reference_type=RefType.EVIDENCE, record_id=evidence_id)),
            trace=trace,
            model_identifier="gemini-test",
            prompt_version="reply-drafter-v1",
        )
    )
    grounding = MagicMock()
    grounding.validate.return_value = (evidence_id,)
    follow_ups = MagicMock()
    follow_ups.get_for_update.return_value = SimpleNamespace(
        id=scope.follow_up_id, project_id=scope.project_id, requirement_id=scope.requirement_id
    )
    requirements = MagicMock()
    requirements.get_for_update.return_value = SimpleNamespace(id=scope.requirement_id, project_id=scope.project_id)
    drafts = MagicMock()
    drafts.find_active_for_follow_up.side_effect = [active_before, active_after]
    drafts.create_generated.return_value = SimpleNamespace(id=uuid4())
    lineage = MagicMock()
    lineage.create_proposal.return_value = SimpleNamespace(id=uuid4())
    contacts = MagicMock()
    contacts.get.return_value = SimpleNamespace(
        id=scope.trusted_contact_id,
        project_id=scope.project_id,
        is_active=True,
        email_normalized="contact@example.com",
    )
    for repository in (follow_ups, requirements, drafts, lineage, contacts):
        repository.session = session
    service = ReplyDraftGenerationService(
        session=session,
        eligibility_service=eligibility,
        scoped_context_service=contexts,
        runner=runner,
        grounding_validator=grounding,
        follow_up_repository=follow_ups,
        requirement_repository=requirements,
        reply_draft_repository=drafts,
        lineage_repository=lineage,
        project_contact_repository=contacts,
    )
    return service, scope, session, runner, grounding, drafts, lineage, contexts


def test_generation_persists_one_grounded_generated_draft_with_authoritative_targeting():
    service, scope, session, runner, grounding, drafts, lineage, contexts = _generation_service()

    result = asyncio.run(service.generate(scope.follow_up_id))

    assert result.status.value == "GENERATED_NEW"
    assert result.ai_proposal_id == lineage.create_proposal.return_value.id
    runner.run.assert_awaited_once_with(contexts.open.return_value)
    assert grounding.validate.call_count == 2
    created = drafts.create_generated.call_args.kwargs
    assert created["follow_up_id"] == scope.follow_up_id
    assert created["source_correspondence_event_id"] == scope.source_correspondence_event_id
    assert created["target_correspondence_event_id"] == scope.source_correspondence_event_id
    assert created["project_contact_id"] == scope.trusted_contact_id
    assert created["recipient_email"] == "contact@example.com"
    assert created["gmail_thread_id"] == scope.gmail_thread_id
    assert created["source_gmail_message_id"] == scope.gmail_message_id
    assert created["generated_subject"] == "Schedule follow-up"
    proposal_values = lineage.create_proposal.call_args.kwargs
    assert proposal_values["proposal_type"] is ProposalType.REPLY_DRAFT
    assert proposal_values["correspondence_event_id"] == scope.source_correspondence_event_id
    assert proposal_values["model_identifier"] == "gemini-test"
    assert proposal_values["prompt_version"] == "reply-drafter-v1"
    assert len(proposal_values["input_hash"]) == 64
    assert proposal_values["evidence_item_ids"] == grounding.validate.return_value
    assert proposal_values["input_metadata"]["successful_tool_trace"]["follow_up_id"] == str(scope.follow_up_id)
    lineage.create_audit_event.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.parametrize("status", tuple(ReplyDraftStatus))
def test_only_active_drafts_short_circuit_before_model(status):
    if status in {ReplyDraftStatus.REJECTED, ReplyDraftStatus.SENT}:
        return
    existing = SimpleNamespace(id=uuid4(), status=status)
    service, scope, _, runner, _, _, lineage, contexts = _generation_service(active_before=existing)

    result = asyncio.run(service.generate(scope.follow_up_id))

    assert result.status.value == "EXISTING_ACTIVE_DRAFT"
    assert result.reply_draft_id == existing.id
    runner.run.assert_not_awaited()
    contexts.open.assert_not_called()
    lineage.create_proposal.assert_not_called()


def test_post_model_active_draft_race_returns_existing_without_proposal():
    existing = SimpleNamespace(id=uuid4(), status=ReplyDraftStatus.GENERATED)
    service, scope, _, runner, _, _, lineage, _ = _generation_service(active_after=existing)

    result = asyncio.run(service.generate(scope.follow_up_id))

    assert result.status.value == "EXISTING_ACTIVE_DRAFT"
    runner.run.assert_awaited_once()
    lineage.create_proposal.assert_not_called()


def test_only_the_active_draft_unique_constraint_is_reconciled_as_a_race():
    service, scope, _, _, _, drafts, lineage, _ = _generation_service()
    existing = SimpleNamespace(id=uuid4(), status=ReplyDraftStatus.GENERATED)
    drafts.find_active_for_follow_up.side_effect = [None, None, existing]
    lineage.create_proposal.side_effect = IntegrityError(
        "insert", {}, Exception("unrelated constraint")
    )

    with pytest.raises(IntegrityError):
        asyncio.run(service.generate(scope.follow_up_id))

    class ActiveDraftUniqueError(Exception):
        diag = SimpleNamespace(constraint_name="uq_reply_drafts_active_follow_up")

    service, scope, _, _, _, drafts, lineage, _ = _generation_service()
    existing = SimpleNamespace(id=uuid4(), status=ReplyDraftStatus.GENERATED)
    drafts.find_active_for_follow_up.side_effect = [None, None, existing]
    lineage.create_proposal.side_effect = IntegrityError("insert", {}, ActiveDraftUniqueError())

    assert asyncio.run(service.generate(scope.follow_up_id)).reply_draft_id == existing.id


def test_stale_scope_or_failed_grounding_never_persists():
    stale_scope = _scope()
    service, scope, session, _, _, _, lineage, _ = _generation_service(fresh_scope=stale_scope)
    with pytest.raises(ReplyDraftGenerationStaleScopeError):
        asyncio.run(service.generate(scope.follow_up_id))
    lineage.create_proposal.assert_not_called()
    session.rollback.assert_called()

    service, scope, _, _, grounding, _, lineage, _ = _generation_service()
    grounding.validate.side_effect = ReplyDraftGroundingValidationError("invalid")
    with pytest.raises(ReplyDraftGroundingValidationError):
        asyncio.run(service.generate(scope.follow_up_id))
    lineage.create_proposal.assert_not_called()


def test_not_draftable_or_runner_failure_creates_no_durable_generation():
    service, scope, _, runner, _, _, lineage, _ = _generation_service()
    service.eligibility.assess.side_effect = [
        ReplyDraftEligibility(
            status=ReplyDraftEligibilityStatus.NOT_DRAFTABLE_IN_S2_V1,
            reason="FOLLOW_UP_NOT_DUE",
        )
    ]
    with pytest.raises(ReplyDraftGenerationNotDraftableError):
        asyncio.run(service.generate(scope.follow_up_id))
    runner.run.assert_not_awaited()
    lineage.create_proposal.assert_not_called()

    service, scope, _, runner, _, _, lineage, _ = _generation_service()
    runner.run.side_effect = RuntimeError("provider exhausted")
    with pytest.raises(RuntimeError, match="provider exhausted"):
        asyncio.run(service.generate(scope.follow_up_id))
    lineage.create_proposal.assert_not_called()


def test_contact_or_persistence_failure_rolls_back_without_partial_generation():
    service, scope, session, _, _, _, lineage, _ = _generation_service()
    service.contacts.get.return_value.is_active = False
    with pytest.raises(ReplyDraftGenerationStaleScopeError, match="trusted contact"):
        asyncio.run(service.generate(scope.follow_up_id))
    lineage.create_proposal.assert_not_called()
    session.rollback.assert_called()

    service, scope, session, _, _, _, lineage, _ = _generation_service()
    lineage.create_audit_event.side_effect = RuntimeError("audit failed")
    with pytest.raises(RuntimeError, match="audit failed"):
        asyncio.run(service.generate(scope.follow_up_id))
    session.rollback.assert_called()


def test_final_grounding_recheck_blocks_evidence_that_changed_after_the_model_run():
    service, scope, _, _, grounding, _, lineage, _ = _generation_service()
    grounding.validate.side_effect = [
        (uuid4(),),
        ReplyDraftGroundingValidationError("evidence is now invalid"),
    ]

    with pytest.raises(ReplyDraftGroundingValidationError, match="now invalid"):
        asyncio.run(service.generate(scope.follow_up_id))

    assert grounding.validate.call_count == 2
    lineage.create_proposal.assert_not_called()


def test_generation_metadata_hash_is_canonical_for_equivalent_json():
    first = {"b": ["value"], "a": {"nested": 1}}
    second = {"a": {"nested": 1}, "b": ["value"]}

    assert ReplyDraftGenerationService._canonical_hash(first) == ReplyDraftGenerationService._canonical_hash(second)
