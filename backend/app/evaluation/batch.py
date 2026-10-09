"""Small sequential runs with JSON-serializable results; no result persistence."""

from collections.abc import Sequence

from sqlalchemy import Engine

from app.core.config import Settings
from app.evaluation.contracts import EvaluationBatchResult, EvaluationCase, EvaluationCaseResult
from app.evaluation.runner import run_evaluation_case
from app.evaluation.scoring import score_evaluation_case


async def run_evaluation_cases(cases: Sequence[EvaluationCase], *, engine: Engine, settings: Settings,
                              project_agent=None, requirement_agent=None) -> EvaluationBatchResult:
    results = []
    for case in cases:
        try:
            result = await run_evaluation_case(case, engine=engine, settings=settings,
                project_agent=project_agent, requirement_agent=requirement_agent)
            results.append(score_evaluation_case(case, result))
        except Exception as exc:
            results.append(EvaluationCaseResult(case_id=case.case_id, status="ERROR",
                error=f"batch execution: {type(exc).__name__}"))
    return EvaluationBatchResult(results=tuple(results))
