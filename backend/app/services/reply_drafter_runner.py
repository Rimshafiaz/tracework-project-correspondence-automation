import asyncio
from dataclasses import dataclass

import httpx
from groq import APIConnectionError as GroqAPIConnectionError
from openai import APIConnectionError as OpenRouterAPIConnectionError
from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

from app.ai.prompts.reply_drafter import REPLY_DRAFTER_PROMPT_VERSION
from app.ai.reply_drafter_context import (
    ReplyDrafterDeps,
    ReplyDrafterRunTrace,
    ReplyDrafterRunTraceAccumulator,
    ScopedReplyDrafterContext,
)
from app.ai.reply_drafter_schemas import ReplyDraftProposal

REPLY_DRAFTER_PROVIDER_ATTEMPTS = 3
REPLY_DRAFTER_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
REPLY_DRAFTER_RETRY_INITIAL_DELAY_SECONDS = 0.5
REPLY_DRAFTER_USAGE_LIMITS = UsageLimits(request_limit=8, tool_calls_limit=6)
REPLY_DRAFTER_RUN_PROMPT = "Draft the reply using approved scoped tools as needed."


@dataclass(frozen=True)
class ReplyDrafterRunResult:
    proposal: ReplyDraftProposal
    trace: ReplyDrafterRunTrace
    model_identifier: str
    prompt_version: str


class ReplyDrafterRunner:
    """Runs the scoped draft-only agent without opening context or persisting data."""

    def __init__(
        self,
        *,
        agent: Agent[ReplyDrafterDeps, ReplyDraftProposal],
        model_identifier: str,
    ) -> None:
        if not model_identifier.strip():
            raise ValueError("model_identifier must not be blank")
        self.agent = agent
        self.model_identifier = model_identifier.strip()

    async def run(
        self,
        scoped_context: ScopedReplyDrafterContext,
    ) -> ReplyDrafterRunResult:
        follow_up_id = scoped_context.get_due_follow_up().follow_up_id
        for attempt in range(REPLY_DRAFTER_PROVIDER_ATTEMPTS):
            trace = ReplyDrafterRunTraceAccumulator(follow_up_id=follow_up_id)
            try:
                run_result = await self.agent.run(
                    REPLY_DRAFTER_RUN_PROMPT,
                    deps=ReplyDrafterDeps(scoped_context=scoped_context, trace=trace),
                    usage_limits=REPLY_DRAFTER_USAGE_LIMITS,
                )
                return ReplyDrafterRunResult(
                    proposal=run_result.output,
                    trace=trace.snapshot(),
                    model_identifier=self.model_identifier,
                    prompt_version=REPLY_DRAFTER_PROMPT_VERSION,
                )
            except Exception as exc:
                if (
                    not self._is_retryable_provider_error(exc)
                    or attempt == REPLY_DRAFTER_PROVIDER_ATTEMPTS - 1
                ):
                    raise
                await asyncio.sleep(
                    REPLY_DRAFTER_RETRY_INITIAL_DELAY_SECONDS * (2**attempt)
                )
        raise AssertionError("provider retry loop completed without a result")

    @staticmethod
    def _is_retryable_provider_error(exc: Exception) -> bool:
        if isinstance(exc, ModelHTTPError):
            return exc.status_code in REPLY_DRAFTER_RETRYABLE_STATUS_CODES
        if isinstance(exc, ModelAPIError) and isinstance(
            exc.__cause__, (GroqAPIConnectionError, OpenRouterAPIConnectionError)
        ):
            return True
        return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))
