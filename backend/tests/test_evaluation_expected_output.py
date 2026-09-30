import pytest
from pydantic import ValidationError

from app.evaluation.contracts import EvaluationExpectedOutput, ExpectedConflict, ExpectedNewRequirement, ExpectedProjectResolution, ExpectedRequirementState
from app.models.enums import RequirementState


def test_expected_output_captures_common_ground_truth() -> None:
    output = EvaluationExpectedOutput(
        project_resolution=ExpectedProjectResolution.MATCHED,
        project_ids=("project-alpha",),
        requirement_states=(
            ExpectedRequirementState(
                requirement_id="requirement-one",
                state=RequirementState.PARTIAL,
            ),
        ),
        new_requirements=(
            ExpectedNewRequirement(
                name="Additional approval",
                evidence_ids=("evidence-two",),
            ),
        ),
        review_required=False,
    )

    assert output.project_ids == ("project-alpha",)
    assert output.requirement_states[0].state is RequirementState.PARTIAL
    assert "confidence" not in EvaluationExpectedOutput.model_fields


@pytest.mark.parametrize(
    ("resolution", "project_ids", "message"),
    [
        (ExpectedProjectResolution.MATCHED, (), "exactly one"),
        (ExpectedProjectResolution.MULTI_PROJECT, ("one",), "at least two"),
        (ExpectedProjectResolution.NO_MATCH, ("one",), "cannot contain"),
    ],
)
def test_project_resolution_requires_consistent_project_ids(
    resolution: ExpectedProjectResolution,
    project_ids: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        EvaluationExpectedOutput(
            project_resolution=resolution,
            project_ids=project_ids,
            review_required=False,
        )


def test_review_resolution_and_conflicts_require_review() -> None:
    with pytest.raises(ValidationError, match="resolution requires review"):
        EvaluationExpectedOutput(
            project_resolution=ExpectedProjectResolution.REVIEW_REQUIRED,
            review_required=False,
        )

    conflict = ExpectedConflict(
        conflict_type="identifier_mismatch",
        evidence_ids=("evidence-one", "evidence-two"),
        description="Two identifiers disagree.",
    )
    with pytest.raises(ValidationError, match="conflict requires review"):
        EvaluationExpectedOutput(
            project_resolution=ExpectedProjectResolution.MATCHED,
            project_ids=("project-alpha",),
            conflicts=(conflict,),
            review_required=False,
        )


def test_expected_requirement_ids_must_be_unique() -> None:
    state = ExpectedRequirementState(
        requirement_id="requirement-one",
        state=RequirementState.OPEN,
    )

    with pytest.raises(ValidationError, match="expected requirement IDs must be unique"):
        EvaluationExpectedOutput(
            project_resolution=ExpectedProjectResolution.MATCHED,
            project_ids=("project-alpha",),
            requirement_states=(state, state),
            review_required=False,
        )
