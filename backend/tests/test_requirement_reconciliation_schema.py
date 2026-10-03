from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.requirement_schemas import ExistingRequirementImpact, NewRequirementProposal, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.models.enums import RequirementState


def _evidence() -> RequirementSourceEvidence:
    return RequirementSourceEvidence(
        correspondence_event_id=uuid4(),
        source_field=ResolverSourceField.BODY,
        excerpt="The report is complete.",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"proposed_state": RequirementState.PARTIAL},
        {"proposed_expected_date": date(2030, 1, 2)},
    ],
)
def test_no_change_cannot_hide_a_state_or_date_change(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="NO_CHANGE"):
        ExistingRequirementImpact(
            requirement_id=uuid4(),
            disposition=RequirementImpactDisposition.NO_CHANGE,
            interpretation="No material change.",
            **changes,
        )


def test_update_requires_an_actual_field_and_evidence() -> None:
    with pytest.raises(ValidationError, match="requires a proposed state or date"):
        ExistingRequirementImpact(
            requirement_id=uuid4(),
            disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
            interpretation="An update was suggested.",
        )

    with pytest.raises(ValidationError, match="requires supporting evidence"):
        ExistingRequirementImpact(
            requirement_id=uuid4(),
            disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
            proposed_state=RequirementState.SATISFIED,
            interpretation="The requirement appears complete.",
        )


def test_update_accepts_grounded_state_or_date_change() -> None:
    evidence = _evidence()
    state_change = ExistingRequirementImpact(
        requirement_id=uuid4(),
        disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
        proposed_state=RequirementState.SATISFIED,
        evidence=(evidence,),
        interpretation="The supplied report completes the requirement.",
    )
    date_change = ExistingRequirementImpact(
        requirement_id=uuid4(),
        disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
        proposed_expected_date=date(2030, 1, 2),
        evidence=(evidence,),
        interpretation="The sender supplied a new expected date.",
    )

    assert state_change.proposed_state is RequirementState.SATISFIED
    assert date_change.proposed_expected_date == date(2030, 1, 2)


def test_source_evidence_has_no_model_generated_offsets() -> None:
    assert "start_offset" not in RequirementSourceEvidence.model_fields
    assert "end_offset" not in RequirementSourceEvidence.model_fields
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RequirementSourceEvidence(
            correspondence_event_id=uuid4(),
            source_field=ResolverSourceField.BODY,
            excerpt="The report is complete.",
            start_offset=0,
        )


def test_new_requirement_requires_evidence_and_output_allows_no_impacts() -> None:
    assert RequirementReconciliation() == RequirementReconciliation()
    with pytest.raises(ValidationError):
        NewRequirementProposal(
            name="Provide a recurring report",
            interpretation="This appears to introduce new scope.",
            evidence=(),
        )
