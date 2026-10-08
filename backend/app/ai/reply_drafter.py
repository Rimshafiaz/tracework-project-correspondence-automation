from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from app.ai.prompts.reply_drafter import REPLY_DRAFTER_INSTRUCTIONS
from app.ai.reply_drafter_context import (
    ReplyDrafterDeps,
    ReplyDrafterToolName,
)
from app.ai.reply_drafter_schemas import (
    ReplyDraftGroundingReference,
    ReplyDraftGroundingReferenceType,
    ReplyDraftProposal,
)
from app.core.config import Settings


def _record(
    ctx: RunContext[ReplyDrafterDeps],
    tool_name: ReplyDrafterToolName,
    result,
    references: tuple[ReplyDraftGroundingReference, ...],
):
    ctx.deps.trace.record(
        tool_name=tool_name,
        result=result.model_dump(mode="json"),
        exposed_references=references,
    )
    return result


def get_due_follow_up(ctx: RunContext[ReplyDrafterDeps]):
    result = ctx.deps.scoped_context.get_due_follow_up()
    return _record(
        ctx,
        ReplyDrafterToolName.GET_DUE_FOLLOW_UP,
        result,
        (
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.FOLLOW_UP,
                record_id=result.follow_up_id,
            ),
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.PROJECT,
                record_id=result.project_id,
            ),
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.REQUIREMENT,
                record_id=result.requirement_id,
            ),
        ),
    )


def get_project_summary(ctx: RunContext[ReplyDrafterDeps]):
    result = ctx.deps.scoped_context.get_project_summary()
    return _record(
        ctx,
        ReplyDrafterToolName.GET_PROJECT_SUMMARY,
        result,
        (
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.PROJECT,
                record_id=result.project_id,
            ),
        ),
    )


def get_requirement_context(ctx: RunContext[ReplyDrafterDeps]):
    result = ctx.deps.scoped_context.get_requirement_context()
    references = [
        ReplyDraftGroundingReference(
            reference_type=ReplyDraftGroundingReferenceType.PROJECT,
            record_id=result.project_id,
        ),
        ReplyDraftGroundingReference(
            reference_type=ReplyDraftGroundingReferenceType.REQUIREMENT,
            record_id=result.requirement_id,
        ),
    ]
    for evidence in result.evidence:
        references.extend(
            (
                ReplyDraftGroundingReference(
                    reference_type=ReplyDraftGroundingReferenceType.EVIDENCE,
                    record_id=evidence.evidence_item_id,
                ),
                ReplyDraftGroundingReference(
                    reference_type=ReplyDraftGroundingReferenceType.CORRESPONDENCE,
                    record_id=evidence.correspondence_event_id,
                ),
            )
        )
    return _record(
        ctx,
        ReplyDrafterToolName.GET_REQUIREMENT_CONTEXT,
        result,
        tuple(references),
    )


def list_recent_correspondence(ctx: RunContext[ReplyDrafterDeps]):
    result = ctx.deps.scoped_context.list_recent_correspondence()
    return _record(
        ctx,
        ReplyDrafterToolName.LIST_RECENT_CORRESPONDENCE,
        result,
        tuple(
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.CORRESPONDENCE,
                record_id=item.correspondence_event_id,
            )
            for item in result.correspondence
        ),
    )


def list_follow_up_history(ctx: RunContext[ReplyDrafterDeps]):
    result = ctx.deps.scoped_context.list_follow_up_history()
    return _record(
        ctx,
        ReplyDrafterToolName.LIST_FOLLOW_UP_HISTORY,
        result,
        tuple(
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.FOLLOW_UP,
                record_id=item.follow_up_id,
            )
            for item in result.follow_ups
        ),
    )


def list_document_revision_status(ctx: RunContext[ReplyDrafterDeps]):
    result = ctx.deps.scoped_context.list_document_revision_status()
    return _record(
        ctx,
        ReplyDrafterToolName.LIST_DOCUMENT_REVISION_STATUS,
        result,
        tuple(
            ReplyDraftGroundingReference(
                reference_type=ReplyDraftGroundingReferenceType.DOCUMENT,
                record_id=item.document_id,
            )
            for item in result.documents
        ),
    )


def build_reply_drafter_agent(settings: Settings) -> Agent[ReplyDrafterDeps, ReplyDraftProposal]:
    if settings.google_api_key is None:
        raise ValueError("GOOGLE_API_KEY is required to build the Reply Drafter Agent")

    model = GoogleModel(
        settings.reply_drafter_model,
        provider=GoogleProvider(api_key=settings.google_api_key.get_secret_value()),
    )
    return Agent(
        model,
        deps_type=ReplyDrafterDeps,
        output_type=ReplyDraftProposal,
        instructions=REPLY_DRAFTER_INSTRUCTIONS,
        model_settings=GoogleModelSettings(temperature=0),
        retries={"output": 2},
        tools=(
            get_due_follow_up,
            get_project_summary,
            get_requirement_context,
            list_recent_correspondence,
            list_follow_up_history,
            list_document_revision_status,
        ),
    )
