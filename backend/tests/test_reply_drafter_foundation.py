from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.prompts.reply_drafter import REPLY_DRAFTER_PROMPT_VERSION
from app.ai.reply_drafter_context import (
    ReplyDrafterRunTraceAccumulator,
    ReplyDrafterToolName,
    ReplyDrafterToolTraceEntry,
)
from app.ai.reply_drafter_schemas import (
    ReplyDraftGroundingReference,
    ReplyDraftGroundingReferenceType,
    ReplyDraftGroundingReferenceType,
    ReplyDraftProposal,
)
from app.contracts.reply_draft_generation import (
    ReplyDraftGenerationResult,
    ReplyDraftGenerationStatus,
)
from app.models.enums import ReplyType


def test_reply_drafter_prompt_version_is_frozen():
    assert REPLY_DRAFTER_PROMPT_VERSION == "reply-drafter-v1"


def test_reply_draft_proposal_is_strict_and_uses_all_grounding_categories():
    references = tuple(
        ReplyDraftGroundingReference(reference_type=kind, record_id=uuid4())
        for kind in ReplyDraftGroundingReferenceType
    )

    proposal = ReplyDraftProposal(
        reply_type=ReplyType.OVERDUE_FOLLOW_UP,
        subject="Schedule follow-up",
        body="Please provide the outstanding schedule.",
        grounding_references=references,
    )

    assert {item.reference_type for item in proposal.grounding_references} == set(
        ReplyDraftGroundingReferenceType
    )
    with pytest.raises(ValidationError):
        ReplyDraftProposal.model_validate({**proposal.model_dump(), "recipient": "x"})
    with pytest.raises(ValidationError):
        ReplyDraftProposal(
            reply_type=ReplyType.OVERDUE_FOLLOW_UP,
            subject=" ",
            body="Body",
            grounding_references=references[:1],
        )


def test_trace_contract_is_bounded_typed_provenance_without_reasoning():
    follow_up_id = uuid4()
    accumulator = ReplyDrafterRunTraceAccumulator(follow_up_id=follow_up_id)
    entry = ReplyDrafterToolTraceEntry(
        tool_name=ReplyDrafterToolName.GET_DUE_FOLLOW_UP,
        result={"follow_up_id": str(follow_up_id), "status": "DUE"},
        exposed_references=(
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.FOLLOW_UP,
                record_id=follow_up_id,
            ),
        ),
    )
    accumulator.entries.append(entry)

    assert accumulator.snapshot().entries == (entry,)


def test_generation_result_distinguishes_new_and_existing_active_drafts():
    ReplyDraftGenerationResult(
        status=ReplyDraftGenerationStatus.GENERATED_NEW,
        reply_draft_id=uuid4(),
        ai_proposal_id=uuid4(),
    )
    ReplyDraftGenerationResult(
        status=ReplyDraftGenerationStatus.EXISTING_ACTIVE_DRAFT,
        reply_draft_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        ReplyDraftGenerationResult(
            status=ReplyDraftGenerationStatus.GENERATED_NEW,
            reply_draft_id=uuid4(),
        )
