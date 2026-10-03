from uuid import uuid4

import pytest

from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal, ProjectCandidateSnapshotError, reconstruct_project_candidate_snapshot, serialize_project_candidate_snapshot
from app.models.enums import ProjectStatus


def _candidate_set() -> ProjectCandidateSet:
    project_id = uuid4()
    source_record_id = uuid4()
    return ProjectCandidateSet(
        candidates=(
            ProjectCandidate(
                project_id=project_id,
                project_code="EXAMPLE",
                project_name="Example Project",
                project_status=ProjectStatus.ACTIVE,
                signals=(
                    ProjectCandidateSignal(
                        signal_type=CandidateSignalType.VERIFIED_IDENTIFIER,
                        matched_value="external-123",
                        source=CandidateSignalSource.PROJECT_RECORD,
                        identifier_type="external_reference",
                        source_record_id=source_record_id,
                        exact=True,
                        verified=True,
                    ),
                    ProjectCandidateSignal(
                        signal_type=CandidateSignalType.FUZZY_ALIAS,
                        matched_value="example",
                        source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                        source_record_id=source_record_id,
                        exact=False,
                        similarity_score=91.5,
                    ),
                ),
            ),
        )
    )


def test_candidate_snapshot_round_trip_preserves_complete_signals() -> None:
    candidates = _candidate_set()

    metadata = serialize_project_candidate_snapshot(candidates)
    reconstructed = reconstruct_project_candidate_snapshot(metadata)

    assert reconstructed == candidates
    assert reconstructed.candidates[0].signals[0].verified is True
    assert reconstructed.candidates[0].signals[1].similarity_score == 91.5


@pytest.mark.parametrize(
    "metadata, message",
    [
        (None, "snapshot is missing"),
        ({}, "version is missing or unsupported"),
        (
            {"project_candidate_snapshot_schema_version": 99},
            "version is missing or unsupported",
        ),
        (
            {"project_candidate_snapshot_schema_version": 1},
            "payload is missing or malformed",
        ),
        (
            {
                "project_candidate_snapshot_schema_version": 1,
                "project_candidate_set": {"candidates": [{"invalid": True}]},
            },
            "payload is invalid",
        ),
    ],
)
def test_candidate_snapshot_rejects_missing_or_malformed_metadata(
    metadata: dict[str, object] | None,
    message: str,
) -> None:
    with pytest.raises(ProjectCandidateSnapshotError, match=message):
        reconstruct_project_candidate_snapshot(metadata)
