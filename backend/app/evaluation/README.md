# Evaluation harness usage

The harness supplies fixture correspondence and project data to production
resolution, reconciliation, policy, and explicitly requested review services.
It records outcomes and checks expectations without duplicating domain rules.
M23 will supply held-out cases; current development fixtures are schema demos,
not a benchmark promised to pass.

Run Python from `backend` with the backend virtual environment. Supply an explicit
PostgreSQL evaluation URL whose role can create schemas. Every case runs in its
own schema inside an outer rollback-only transaction, including service commits.
No case data or result is persisted. Gmail/Drive integrations are not invoked;
without injected test agents, selected model stages may make real provider calls.
The executable runner covers Tracework; it does not add A/B comparison orchestration.

## One case and a batch

An `EvaluationCase` contains `case_id`, `title`, `category`, `input`, `expected`,
`safety`, and ordered `stages`. `input` defines correspondence, candidate projects,
requirements, and evidence using stable fixture IDs. Expected IDs must reference
those fixtures. Omitted optional expectations are not checked; an explicitly
supplied `expected_date: null` expects no date. Project/evidence ordering is ignored.
`allowed_actions` is a whitelist, not a list of required actions; `must_not` and
no-mutation/no-filing flags add safety checks. Conflict descriptions are not scored.

This single example defines a read-only case from an existing fixture, runs it,
scores it, and runs a sequential batch:

```python
import asyncio
import os
from sqlalchemy import create_engine
from app.core.config import Settings
from app.evaluation import EvaluationCase, score_evaluation_case
from app.evaluation.datasets import DatasetSplit, load_dataset
from app.evaluation.runner import run_evaluation_case
from app.evaluation.batch import run_evaluation_cases

async def main():
    payload = load_dataset(DatasetSplit.DEVELOPMENT)[0].model_dump(mode="json")
    payload.update(case_id="project-only", stages=["PROJECT_RESOLUTION"],
                   expected={"project_resolution": "MATCHED", "project_ids": ["project-alpha"],
                             "review_required": False},
                   safety={"require_no_authoritative_mutation": True})
    case = EvaluationCase.model_validate(payload)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        unscored = await run_evaluation_case(case, engine=engine, settings=Settings())
        print(score_evaluation_case(case, unscored).model_dump_json(indent=2))
        batch = await run_evaluation_cases([case], engine=engine, settings=Settings())
        print(batch.model_dump_json(indent=2))  # Runs the case again; counts + results.
    finally:
        engine.dispose()

asyncio.run(main())
```

Cases start with project resolution. Reconciliation requires the policy stage to
authorize its project scope and currently supports one authorized project.
`REVIEW_APPLICATION` requires an explicit `review_action` (`APPROVE` or `REJECT`).
Expected/actual `review_application_status` is `APPROVED`, `REJECTED`, or `BLOCKED`.
For an expected retraction block, set it to `BLOCKED` and set
`application_block_code` to `REMAINING_SUPPORTING_EVIDENCE`. Known production review
domain exceptions are observable blocks; uncoded domain blocks have no reason code.
Unexpected exceptions are never converted into expected blocks.

## Results

- `UNSCORED`: execution completed and actual outcomes exist; expectations not checked.
- `PASS`: all applicable expectations and safety checks matched.
- `FAIL`: execution completed, but checks differ (`check`, `expected`, `actual`).
- `ERROR`: setup, provider, database, or unexpected execution failure; never scored as FAIL.

Scoring reuses captured outcomes and performs no network/database calls. Batches
run sequentially, continue after FAIL/ERROR, and return `total`, `passed`, `failed`,
`errors`, and ordered `results`. No CLI, result database, or external judge is needed.

For focused tests, run `python -m pytest -q -p no:cacheprovider --basetemp=.pytest-evaluation`
with the `tests/test_evaluation_*.py` files. PostgreSQL runner tests require
`TEST_DATABASE_URL`; they use fake models and rollback-only schemas.
