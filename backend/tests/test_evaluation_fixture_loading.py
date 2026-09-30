from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.contracts import EvaluationCase, EvaluationCategory
from app.evaluation.datasets import DatasetSplit, load_case, load_dataset, load_manifest


def test_development_examples_load_and_held_out_remains_empty() -> None:
    development_cases = load_dataset(DatasetSplit.DEVELOPMENT)
    held_out_cases = load_dataset(DatasetSplit.HELD_OUT)

    assert len(development_cases) == 3
    assert {case.category for case in development_cases} == {
        EvaluationCategory.CLEAR_CORRESPONDENCE,
        EvaluationCategory.CONFLICTING_EVIDENCE,
        EvaluationCategory.PARTIAL_FULFILLMENT,
    }
    assert held_out_cases == ()
    assert load_manifest(DatasetSplit.HELD_OUT).case_files == ()


def test_case_rejects_ground_truth_that_references_missing_input() -> None:
    case = load_dataset(DatasetSplit.DEVELOPMENT)[0]
    invalid_expected = case.expected.model_copy(
        update={"project_ids": ("missing-project",)}
    )

    with pytest.raises(ValidationError, match="expected projects must exist"):
        EvaluationCase(
            case_id=case.case_id,
            title=case.title,
            category=case.category,
            input=case.input,
            expected=invalid_expected,
            safety=case.safety,
        )


def test_load_case_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"case_id": "incomplete"}', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_case(path)
