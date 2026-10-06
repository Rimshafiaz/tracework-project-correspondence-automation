import json
from pathlib import Path


RESULT_PATH = (
    Path(__file__).parents[1]
    / "evaluation_results"
    / "development"
    / "m17_core_integration.json"
)


def test_m17_development_result_is_not_a_final_benchmark_and_covers_core_cases():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["evaluation_kind"] == "development_deterministic_integration"
    assert result["final_benchmark"] is False
    assert len(result["cases"]) == 11
    assert all(case["result"] == "PASS" for case in result["cases"])
    assert not any(case["dangerous_automatic_action"] for case in result["cases"])
    assert {case["category"] for case in result["cases"]} == {
        "EXACT_PROJECT_IDENTITY",
        "AMBIGUOUS_PROJECT_IDENTITY",
        "BODY_ATTACHMENT_IDENTITY_CONFLICT",
        "INSUFFICIENT_IDENTITY",
        "SAFE_REQUIREMENT_TRANSITION",
        "SATISFIED_REQUIRES_REVIEW",
        "EXPECTED_DATE_REQUIRES_REVIEW",
        "NEW_REQUIREMENT",
        "REQUIREMENT_SEMANTIC_CONCERN",
        "IDEMPOTENT_RETRY",
        "MULTI_PROJECT",
    }
