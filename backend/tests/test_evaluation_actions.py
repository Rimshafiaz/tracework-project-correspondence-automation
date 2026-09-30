from dataclasses import FrozenInstanceError

import pytest

from app.evaluation.actions import ActionType, DangerousFailureType, DANGEROUS_FAILURE_DEFINITIONS


def test_action_values_are_unique_and_project_agnostic() -> None:
    values = [action.value for action in ActionType]

    assert len(values) == len(set(values))
    assert ActionType.CREATE_REVIEW in ActionType
    assert all("ADDRESS" not in value and "REPOSITORY" not in value for value in values)


def test_every_dangerous_failure_has_one_frozen_definition() -> None:
    definitions_by_type = {
        definition.failure_type: definition
        for definition in DANGEROUS_FAILURE_DEFINITIONS
    }

    assert set(definitions_by_type) == set(DangerousFailureType)
    assert len(definitions_by_type) == len(DANGEROUS_FAILURE_DEFINITIONS)
    assert all(definition.description for definition in DANGEROUS_FAILURE_DEFINITIONS)
    assert all(definition.related_actions for definition in DANGEROUS_FAILURE_DEFINITIONS)

    with pytest.raises(FrozenInstanceError):
        definitions_by_type[
            DangerousFailureType.FALSE_REQUIREMENT_CLOSURE
        ].description = "changed"


def test_duplicate_business_action_applies_to_every_action_type() -> None:
    definition = next(
        item
        for item in DANGEROUS_FAILURE_DEFINITIONS
        if item.failure_type is DangerousFailureType.DUPLICATE_BUSINESS_ACTION
    )

    assert set(definition.related_actions) == set(ActionType)
