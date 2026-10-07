import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.enums import CorrespondenceProcessingState, PolicyDecision, ProposalType, ReviewStatus
from app.services.core_correspondence_workflow import CoreCorrespondenceWorkflowService, CoreWorkflowStatus


def _dependencies(*, project_decision=PolicyDecision.ALLOW_AUTO_ACTION, with_filing=False):
    event_id = uuid4()
    project_id = uuid4()
    link = SimpleNamespace(id=uuid4(), project_id=project_id)
    project_proposal = SimpleNamespace(id=uuid4(), input_metadata={})
    requirement_proposal = SimpleNamespace(
        id=uuid4(), input_metadata={"project_id": str(project_id)}
    )
    project_evaluation = SimpleNamespace(id=uuid4(), decision=project_decision)
    requirement_evaluation = SimpleNamespace(
        id=uuid4(), decision=PolicyDecision.ALLOW_AUTO_ACTION
    )
    transition = SimpleNamespace(id=uuid4())
    event = SimpleNamespace(
        id=event_id,
        processing_state=CorrespondenceProcessingState.PENDING,
    )
    session = MagicMock()
    correspondence = MagicMock()
    correspondence.get_for_update.return_value = event

    def update_state(item, *, state, failure_metadata=None):
        item.processing_state = state
        item.failure_metadata = failure_metadata
        return item

    correspondence.update_processing_state.side_effect = update_state
    lineage = MagicMock()
    lineage.list_proposals_for_event.side_effect = lambda **kwargs: (
        [] if kwargs["proposal_type"] is ProposalType.PROJECT_RESOLUTION else []
    )
    project_context = MagicMock()
    project_context.build.return_value = SimpleNamespace()
    project_resolution = MagicMock()
    project_resolution.resolve = AsyncMock(
        return_value=SimpleNamespace(proposal=project_proposal)
    )
    project_workflow = MagicMock()
    project_workflow.process.return_value = SimpleNamespace(
        authorization=SimpleNamespace(
            evaluation=project_evaluation,
            project_links=(link,) if project_decision is PolicyDecision.ALLOW_AUTO_ACTION else (),
        ),
        review_item=None,
    )
    requirement_context = MagicMock()
    requirement_context.build.return_value = SimpleNamespace()
    requirement_reconciliation = MagicMock()
    requirement_reconciliation.reconcile = AsyncMock(
        return_value=SimpleNamespace(proposal=requirement_proposal)
    )
    requirement_workflow = MagicMock()
    requirement_workflow.process.return_value = SimpleNamespace(
        authorization=SimpleNamespace(
            evaluation=requirement_evaluation,
            transition=transition,
        ),
        review=None,
    )
    project_links = MagicMock()
    document_filing = MagicMock() if with_filing else None
    if document_filing is not None:
        document_filing.file_for_project_resolution.return_value = SimpleNamespace(
            outcomes=(SimpleNamespace(status="FILED"),)
        )
    service = CoreCorrespondenceWorkflowService(
        session=session,
        correspondence_repository=correspondence,
        project_link_repository=project_links,
        lineage_repository=lineage,
        project_context_service=project_context,
        project_resolution_service=project_resolution,
        project_workflow_service=project_workflow,
        requirement_context_service=requirement_context,
        requirement_reconciliation_service=requirement_reconciliation,
        requirement_workflow_service=requirement_workflow,
        document_filing_service=document_filing,
    )
    return SimpleNamespace(**locals())


def test_document_filing_runs_after_project_authorization_and_before_completion():
    deps = _dependencies(with_filing=True)

    result = asyncio.run(deps.service.process(deps.event_id))

    deps.document_filing.file_for_project_resolution.assert_called_once_with(
        proposal_id=deps.project_proposal.id,
        policy_evaluation_id=deps.project_evaluation.id,
    )
    assert len(result.document_filing_outcomes) == 1


def test_retryable_drive_failure_does_not_prevent_correspondence_completion():
    deps = _dependencies(with_filing=True)
    deps.document_filing.file_for_project_resolution.return_value.outcomes = (
        SimpleNamespace(status="RETRYABLE_FAILURE"),
    )

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.COMPLETED
    assert deps.event.processing_state is CorrespondenceProcessingState.COMPLETED
    deps.requirement_reconciliation.reconcile.assert_awaited_once()
    deps.requirement_workflow.process.assert_called_once()


def test_pending_project_review_never_invokes_document_filing():
    deps = _dependencies(
        project_decision=PolicyDecision.REVIEW_REQUIRED,
        with_filing=True,
    )
    deps.project_workflow.process.return_value.review_item = SimpleNamespace(
        id=uuid4(), status=ReviewStatus.PENDING
    )

    asyncio.run(deps.service.process(deps.event_id))

    deps.document_filing.file_for_project_resolution.assert_not_called()


def test_allowed_project_continues_through_requirement_policy_once():
    deps = _dependencies()

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.COMPLETED
    assert result.project_link_ids == (deps.link.id,)
    assert result.requirement_outcomes[0].decision is PolicyDecision.ALLOW_AUTO_ACTION
    deps.project_resolution.resolve.assert_awaited_once()
    deps.project_workflow.process.assert_called_once_with(deps.project_proposal.id)
    deps.requirement_reconciliation.reconcile.assert_awaited_once()
    deps.requirement_workflow.process.assert_called_once_with(
        deps.requirement_proposal.id
    )
    assert deps.event.processing_state is CorrespondenceProcessingState.COMPLETED


def test_pending_project_review_stops_requirement_processing_and_is_retryable():
    deps = _dependencies(project_decision=PolicyDecision.REVIEW_REQUIRED)
    review = SimpleNamespace(id=uuid4(), status=ReviewStatus.PENDING)
    deps.project_workflow.process.return_value.review_item = review

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.REVIEW_REQUIRED
    assert result.project_review_item_id == review.id
    assert deps.event.processing_state is CorrespondenceProcessingState.PENDING
    deps.requirement_reconciliation.reconcile.assert_not_awaited()
    deps.requirement_workflow.process.assert_not_called()


def test_resolved_project_review_resumes_with_authoritative_links():
    deps = _dependencies(project_decision=PolicyDecision.REVIEW_REQUIRED)
    review = SimpleNamespace(id=uuid4(), status=ReviewStatus.CORRECTED)
    deps.project_workflow.process.return_value.review_item = review
    deps.project_links.list_approved_project_ids_for_event.return_value = (
        deps.project_id,
    )
    deps.project_links.get_approved_link.return_value = deps.link

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.COMPLETED
    assert result.project_link_ids == (deps.link.id,)
    deps.requirement_reconciliation.reconcile.assert_awaited_once()


def test_project_rejection_never_runs_requirement_processing():
    deps = _dependencies(project_decision=PolicyDecision.REJECT_PROPOSAL)

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.REJECTED
    deps.requirement_reconciliation.reconcile.assert_not_awaited()
    assert deps.event.processing_state is CorrespondenceProcessingState.COMPLETED


def test_existing_proposals_are_reused_after_partial_failure():
    deps = _dependencies()
    deps.event.processing_state = CorrespondenceProcessingState.RETRYABLE_FAILURE
    deps.lineage.list_proposals_for_event.side_effect = lambda **kwargs: (
        [deps.project_proposal]
        if kwargs["proposal_type"] is ProposalType.PROJECT_RESOLUTION
        else [deps.requirement_proposal]
    )

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.COMPLETED
    deps.project_resolution.resolve.assert_not_awaited()
    deps.requirement_reconciliation.reconcile.assert_not_awaited()
    deps.project_workflow.process.assert_called_once_with(deps.project_proposal.id)
    deps.requirement_workflow.process.assert_called_once_with(
        deps.requirement_proposal.id
    )


def test_completed_event_is_a_no_op():
    deps = _dependencies()
    deps.event.processing_state = CorrespondenceProcessingState.COMPLETED

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.ALREADY_COMPLETED
    deps.project_resolution.resolve.assert_not_awaited()
    deps.project_workflow.process.assert_not_called()
    deps.requirement_reconciliation.reconcile.assert_not_awaited()


def test_failure_records_sanitized_retryable_stage_without_losing_durable_work():
    deps = _dependencies()
    deps.requirement_reconciliation.reconcile.side_effect = RuntimeError(
        "provider secret detail"
    )

    with pytest.raises(RuntimeError, match="provider secret detail"):
        asyncio.run(deps.service.process(deps.event_id))

    assert deps.event.processing_state is CorrespondenceProcessingState.RETRYABLE_FAILURE
    assert deps.event.failure_metadata == {
        "stage": f"requirement_reconciliation:{deps.project_id}",
        "error_type": "RuntimeError",
    }
    assert "secret" not in str(deps.event.failure_metadata)


def test_requirement_review_is_returned_without_second_authoritative_path():
    deps = _dependencies()
    review = SimpleNamespace(review_item=SimpleNamespace(id=uuid4()))
    deps.requirement_workflow.process.return_value.authorization.evaluation.decision = (
        PolicyDecision.REVIEW_REQUIRED
    )
    deps.requirement_workflow.process.return_value.review = review

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.status is CoreWorkflowStatus.COMPLETED
    assert result.requirement_outcomes[0].decision is PolicyDecision.REVIEW_REQUIRED
    assert result.requirement_outcomes[0].review_item_id == review.review_item.id


def test_multi_project_authorization_reconciles_every_authorized_project():
    deps = _dependencies()
    second_project_id = uuid4()
    second_link = SimpleNamespace(id=uuid4(), project_id=second_project_id)
    deps.project_workflow.process.return_value.authorization.project_links = (
        deps.link,
        second_link,
    )
    second_proposal = SimpleNamespace(
        id=uuid4(), input_metadata={"project_id": str(second_project_id)}
    )
    deps.requirement_reconciliation.reconcile.side_effect = (
        SimpleNamespace(proposal=deps.requirement_proposal),
        SimpleNamespace(proposal=second_proposal),
    )

    result = asyncio.run(deps.service.process(deps.event_id))

    assert result.project_link_ids == (deps.link.id, second_link.id)
    assert len(result.requirement_outcomes) == 2
    assert deps.requirement_context.build.call_count == 2
    assert deps.requirement_workflow.process.call_count == 2


def test_second_processing_attempt_after_completion_creates_no_second_business_action():
    deps = _dependencies()

    first = asyncio.run(deps.service.process(deps.event_id))
    second = asyncio.run(deps.service.process(deps.event_id))

    assert first.status is CoreWorkflowStatus.COMPLETED
    assert second.status is CoreWorkflowStatus.ALREADY_COMPLETED
    deps.project_resolution.resolve.assert_awaited_once()
    deps.project_workflow.process.assert_called_once()
    deps.requirement_reconciliation.reconcile.assert_awaited_once()
    deps.requirement_workflow.process.assert_called_once()
