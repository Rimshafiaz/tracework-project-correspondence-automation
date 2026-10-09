from pathlib import Path
import asyncio
from collections import Counter
from hashlib import sha256
import json
import os
import re

import pytest

from app.evaluation.contracts import EvaluationStage
from app.evaluation.datasets import DatasetSplit, load_dataset
from app.evaluation.datasets import dataset_directory, load_manifest
from app.evaluation.runner import _seed_case
from app.evaluation.scoring import _matches_action
from app.models import ProjectIdentifier
from app.normalization.project_identity import normalize_identifier, normalize_project_name


@pytest.mark.parametrize("case", load_dataset(DatasetSplit.HELD_OUT), ids=lambda case: case.case_id)
def test_held_out_case_is_self_contained_and_structurally_seedable(case):
    class RecordingSession:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

        def flush(self):
            pass

    session = RecordingSession()
    event, labels = _seed_case(session, case)
    assert event.external_event_id == case.input.correspondence.external_event_id
    assert case.stages[0] is EvaluationStage.PROJECT_RESOLUTION
    assert case.stages == tuple(sorted(case.stages, key=list(EvaluationStage).index))
    assert EvaluationStage.POLICY in case.stages
    if case.case_id in {"EVAL-16", "EVAL-17", "EVAL-18", "EVAL-19"}:
        assert EvaluationStage.REVIEW_APPLICATION in case.stages
        assert case.review_action.value == "APPROVE"
    else:
        assert EvaluationStage.REVIEW_APPLICATION not in case.stages
        assert case.review_action is None
    assert len({row.id for row in session.rows}) == len(session.rows)
    assert set(labels.values()) >= {project.project_id for project in case.input.candidate_projects}
    assert len({project.project_code for project in case.input.candidate_projects}) == len(case.input.candidate_projects)
    for action in case.safety.required_actions:
        assert any(_matches_action(allowed, action) for allowed in case.safety.allowed_actions)
        assert not any(_matches_action(forbidden, action) for forbidden in case.safety.must_not)
    for project in case.input.candidate_projects:
        assert project.normalized_name == normalize_project_name(project.name)
        for identifier in project.identifiers:
            assert identifier.normalized_value == normalize_identifier(identifier.identifier_type, identifier.display_value)
    if case.case_id == "EVAL-06":
        assert [row.verified for row in session.rows if isinstance(row, ProjectIdentifier)] == [False]
        assert case.expected.project_resolution.value == "NO_MATCH"
        assert case.safety.require_no_authoritative_mutation


def test_held_out_wording_and_identities_are_not_copied_from_existing_material():
    backend = Path(__file__).resolve().parents[1]
    files = list((backend / "tests").glob("test_*.py"))
    files += list((backend / "app" / "ai").rglob("*.md"))
    files += list((backend / "app" / "ai").rglob("*.txt"))
    files += list((backend / "app" / "ai" / "prompts").rglob("*.py"))
    files += list((backend / "evaluation_data" / "development").glob("*.json"))
    files += list((backend.parent / "docs").glob("*SMOKE*.md"))
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in files)
    cases = load_dataset(DatasetSplit.HELD_OUT)
    assert len({case.input.correspondence.body for case in cases}) == 20
    first_half = "\n".join(case.model_dump_json() for case in cases[:10])
    for case in cases:
        assert case.input.correspondence.body not in corpus
        assert case.input.correspondence.sender_identifier not in corpus
        for date in set(re.findall(r"\b20\d{2}-\d{2}-\d{2}", case.model_dump_json())):
            assert date not in corpus
        for project in case.input.candidate_projects:
            assert project.name not in corpus
            assert project.project_code not in corpus
            if case in cases[10:]:
                assert project.name not in first_half
                assert project.project_code not in first_half
        if case in cases[10:]:
            assert case.input.correspondence.sender_identifier not in first_half
            for requirement in case.input.requirements:
                assert requirement.name not in first_half


def test_retraction_expectations_require_full_invalidation_or_explicit_block():
    cases = {case.case_id: case for case in load_dataset(DatasetSplit.HELD_OUT)}
    retraction = cases["EVAL-18"]
    targeted = set(retraction.expected.corrections[0].target_evidence_ids)
    assert targeted == {action.target_id for action in retraction.safety.required_actions}
    assert all(action.action_type.value == "INVALIDATE_EVIDENCE" for action in retraction.safety.required_actions)
    blocked = cases["EVAL-19"]
    assert blocked.expected.review_application_status == "BLOCKED"
    assert blocked.expected.application_block_code == "REMAINING_SUPPORTING_EVIDENCE"
    assert any(action.action_type.value == "INVALIDATE_EVIDENCE" for action in blocked.safety.must_not)


def test_frozen_manifest_is_complete_hashed_and_matches_difficulty_mix():
    directory = dataset_directory(DatasetSplit.HELD_OUT)
    manifest = load_manifest(DatasetSplit.HELD_OUT)
    assert set(manifest.case_files) == {path.name for path in directory.glob("*.json") if path.name != "manifest.json"}
    payload = {name: json.loads((directory / name).read_text(encoding="utf-8")) for name in manifest.case_files}
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert manifest.content_hash == f"sha256:{digest}"
    slots = [line.split("|")[3].strip() for line in (directory / "COVERAGE.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| EVAL-")]
    assert len(slots) == 20
    assert Counter(slots) == {"Easy": 6, "Medium": 8, "Hard": 6}
    cases = load_dataset(DatasetSplit.HELD_OUT)
    assert [case.case_id for case in cases if any(item.source_correspondence_grounding for item in case.expected.new_requirements)] == ["EVAL-07"]
    assert [case.case_id for case in cases if case.safety.required_actions] == ["EVAL-16", "EVAL-17", "EVAL-18"]
    assert len({case.input.correspondence.external_event_id for case in cases}) == 20
    all_projects = [item.project_id for case in cases for item in case.input.candidate_projects]
    assert len(set(all_projects)) == len(all_projects)


def test_full_manifest_scoring_and_batch_contracts_accept_controlled_outcomes(monkeypatch):
    from app.evaluation.batch import run_evaluation_cases
    from test_evaluation_scoring import _result, _source_grounded_result

    cases = load_dataset(DatasetSplit.HELD_OUT)
    calls = []

    async def controlled_run(case, **kwargs):
        calls.append(case.case_id)
        if case.case_id == "EVAL-07":
            return _source_grounded_result(case)
        return _result(case, actions=case.safety.required_actions,
            policy={"policy_version": "contract-check", "decision": case.expected.policy_decision,
                "triggered_rule_ids": (), "reasons": ()})

    monkeypatch.setattr("app.evaluation.batch.run_evaluation_case", controlled_run)
    batch = asyncio.run(run_evaluation_cases(cases, engine=None, settings=None))
    assert calls == [case.case_id for case in cases]
    assert all(result.status.value == "PASS" for result in batch.results)
    blocked = next(result for result in batch.results if result.case_id == "EVAL-19")
    assert blocked.actual.review_application_status == "BLOCKED" and blocked.error is None


def test_postgresql_fixtures_rollback_without_case_contamination():
    from sqlalchemy import create_engine, text
    from app.evaluation.runner import _case_session
    from app.evaluation.project_resolver import _fixture_uuid

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL fixture validation")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        for case in load_dataset(DatasetSplit.HELD_OUT):
            with _case_session(engine, case.case_id) as session:
                _seed_case(session, case)
                session.commit()
            schema = f"tracework_eval_{_fixture_uuid('case', case.case_id).hex}"
            with engine.connect() as connection:
                assert not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :name)"), {"name": schema})
    finally:
        engine.dispose()
