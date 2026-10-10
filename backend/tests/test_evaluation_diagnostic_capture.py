import asyncio
from types import SimpleNamespace

from pydantic_ai.exceptions import ModelHTTPError

from app.core.config import Settings
from app.evaluation.runner import _CaptureAgent, _diagnostic_error
from app.ai.schemas import CandidateSignalReference, ProjectResolverInput
from test_evaluation_runner import ProjectAgent, _case, _run, _assert_clean, engine


def test_observer_preserves_output_usage_and_single_call():
    output = _case().expected
    calls = []

    class Agent:
        async def run(self, prompt):
            calls.append(prompt)
            return SimpleNamespace(output=output, usage=SimpleNamespace(requests=1, input_tokens=12, output_tokens=7))

    records = []
    settings = Settings(_env_file=None, database_url="postgresql://unused/test")
    result = asyncio.run(_CaptureAgent(Agent(), "project_resolver", settings, records).run("controlled input"))
    assert result.output is output
    assert calls == ["controlled input"]
    assert records[0]["output"] == output.model_dump(mode="json")
    assert records[0]["usage"] == {"requests": 1, "input_tokens": 12, "output_tokens": 7}


def test_provider_diagnostic_is_bounded_redacted_and_unknown_messages_are_not_copied():
    settings = Settings(_env_file=None, database_url="postgresql://unused/test", google_api_key="private-key")
    error = ModelHTTPError(503, "configured-model", {"message": "private-key " + "x" * 3000})
    diagnostic = _diagnostic_error(error, settings)
    assert diagnostic["http_status"] == 503
    assert len(diagnostic["message"]) <= 2000
    assert "private-key" not in diagnostic["message"]
    assert _diagnostic_error(RuntimeError("private provider dump"), settings) == {"exception": "RuntimeError"}


def test_failed_validation_retains_exact_output_and_reason_after_rollback(engine):
    class WrongSignalAgent(ProjectAgent):
        async def run(self, prompt):
            result = await super().run(prompt)
            evidence = result.output.evidence[0]
            reference = evidence.signal_references[0].model_copy(update={"matched_value": "unsupplied-value"})
            changed = evidence.model_copy(update={"signal_references": (reference,)})
            return SimpleNamespace(output=result.output.model_copy(update={"evidence": (changed,)}))

    case = _case()
    result = _run(engine, case, project_agent=WrongSignalAgent())
    assert result.status.value == "ERROR"
    details = result.execution_details
    assert details["failure"]["message"] == "resolver returned a candidate signal that was not supplied"
    assert details["model_runs"][0]["output"]["evidence"][0]["signal_references"][0]["matched_value"] == "unsupplied-value"
    assert details["project_candidates"]["candidates"]
    assert result.actual is None
    _assert_clean(engine, case)


def test_selected_source_excerpt_and_lineage_survive_case_cleanup(engine):
    case = _case()
    result = _run(engine, case)
    assert result.status.value == "UNSCORED", result.error
    sources = [item for item in result.execution_details["selected_evidence"] if item["source_type"] == "body"]
    assert len(sources) == 1
    assert sources[0]["excerpt"] == case.input.correspondence.body
    assert sources[0]["project_id"] == "project-alpha"
    assert sources[0]["validity"] == "VALID"
    _assert_clean(engine, case)
