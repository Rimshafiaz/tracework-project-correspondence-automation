from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.schemas import ResolverCorrespondence
from app.contracts.requirement_reconciliation import RequirementContextLimitKind, RequirementContextLimitOutcome, RequirementContextSnapshotError, RequirementReconcilerInput, RequirementSnapshot, reconstruct_requirement_context_snapshot, serialize_requirement_context_snapshot
from app.models.enums import RequirementState


def _context() -> RequirementReconcilerInput:
    return RequirementReconcilerInput(
        project_id=uuid4(),
        authoritative_project_link_id=uuid4(),
        correspondence=ResolverCorrespondence(
            correspondence_event_id=uuid4(),
            source="fixture",
            sender_identifier="sender@example.test",
            subject="Status update",
            body="The report is complete.",
            received_at=datetime.now(UTC),
        ),
        requirements=(
            RequirementSnapshot(
                requirement_id=uuid4(),
                name="Provide report",
                current_state=RequirementState.OPEN,
            ),
        ),
    )


def test_requirement_context_snapshot_round_trip() -> None:
    context = _context()

    snapshot = reconstruct_requirement_context_snapshot(
        serialize_requirement_context_snapshot(context)
    )

    assert snapshot.project_id == context.project_id
    assert snapshot.requirements == context.requirements
    assert snapshot.body_sha256 != context.correspondence.body


@pytest.mark.parametrize(
    "metadata,message",
    [
        (None, "snapshot is missing"),
        ({}, "version is missing or unsupported"),
        (
            {"requirement_context_snapshot_schema_version": 1},
            "payload is missing or malformed",
        ),
        (
            {
                "requirement_context_snapshot_schema_version": 1,
                "requirement_reconciliation_context": {"invalid": True},
            },
            "payload is invalid",
        ),
    ],
)
def test_requirement_context_snapshot_rejects_bad_metadata(
    metadata: dict[str, object] | None,
    message: str,
) -> None:
    with pytest.raises(RequirementContextSnapshotError, match=message):
        reconstruct_requirement_context_snapshot(metadata)


def test_context_limit_is_an_explicit_operational_outcome() -> None:
    outcome = RequirementContextLimitOutcome(
        limit_kind=RequirementContextLimitKind.REQUIREMENT_COUNT,
        configured_limit=25,
        actual_value=26,
        reason="Too many requirements for one bounded reconciliation run.",
    )

    assert outcome.actual_value > outcome.configured_limit
    with pytest.raises(ValidationError, match="must exceed"):
        RequirementContextLimitOutcome(
            limit_kind=RequirementContextLimitKind.REQUIREMENT_COUNT,
            configured_limit=25,
            actual_value=25,
            reason="Not exceeded",
        )
