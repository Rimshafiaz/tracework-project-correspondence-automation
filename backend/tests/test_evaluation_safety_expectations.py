import pytest
from pydantic import ValidationError

from app.evaluation.actions import ActionType
from app.evaluation.contracts import ActionExpectation, SafetyExpectations


def test_safety_expectations_describe_allowed_and_forbidden_effects() -> None:
    expectations = SafetyExpectations(
        allowed_actions=(
            ActionExpectation(
                action_type=ActionType.CHANGE_REQUIREMENT_STATE,
                target_type="requirement",
                target_id="requirement-one",
                parameters={"state": "PARTIAL"},
            ),
        ),
        must_not=(
            ActionExpectation(
                action_type=ActionType.CHANGE_REQUIREMENT_STATE,
                target_type="requirement",
                target_id="requirement-one",
                parameters={"state": "SATISFIED"},
            ),
        ),
    )

    assert expectations.allowed_actions[0].parameters["state"] == "PARTIAL"
    assert expectations.must_not[0].parameters["state"] == "SATISFIED"


def test_same_exact_action_cannot_be_allowed_and_forbidden() -> None:
    action = ActionExpectation(action_type=ActionType.FILE_DOCUMENT)

    with pytest.raises(ValidationError, match="both allowed and forbidden"):
        SafetyExpectations(allowed_actions=(action,), must_not=(action,))


def test_no_mutation_still_allows_review_creation() -> None:
    expectations = SafetyExpectations(
        allowed_actions=(
            ActionExpectation(action_type=ActionType.CREATE_REVIEW),
        ),
        require_no_authoritative_mutation=True,
        require_no_document_filing=True,
    )

    assert expectations.require_no_authoritative_mutation is True


def test_no_mutation_rejects_an_allowed_state_change() -> None:
    with pytest.raises(ValidationError, match="cannot allow authoritative actions"):
        SafetyExpectations(
            allowed_actions=(
                ActionExpectation(
                    action_type=ActionType.CHANGE_REQUIREMENT_STATE,
                ),
            ),
            require_no_authoritative_mutation=True,
        )


def test_no_filing_rejects_allowed_filing_actions() -> None:
    with pytest.raises(ValidationError, match="cannot allow document filing"):
        SafetyExpectations(
            allowed_actions=(
                ActionExpectation(action_type=ActionType.FILE_DOCUMENT),
            ),
            require_no_document_filing=True,
        )
