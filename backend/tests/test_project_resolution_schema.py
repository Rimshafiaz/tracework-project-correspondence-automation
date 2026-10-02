from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.schemas import ProjectResolution, ProjectResolverInput, ResolutionConcern, ResolutionEvidence, ResolutionStatus, ResolverCorrespondence
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal
from app.models.enums import ProjectStatus


def _context(candidate_count: int = 1) -> ProjectResolverInput:
    candidates = tuple(
        ProjectCandidate(
            project_id=uuid4(),
            project_code=f"PROJECT-{index}",
            project_name=f"Example Project {index}",
            project_status=ProjectStatus.ACTIVE,
            signals=(
                ProjectCandidateSignal(
                    signal_type=CandidateSignalType.PROJECT_CODE,
                    matched_value=f"PROJECT-{index}",
                    source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                    exact=True,
                ),
            ),
        )
        for index in range(candidate_count)
    )
    return ProjectResolverInput(
        correspondence=ResolverCorrespondence(
            correspondence_event_id=uuid4(),
            source="fixture",
            sender_identifier="sender@example.test",
            body="Example correspondence",
            received_at=datetime.now(UTC),
        ),
        candidates=ProjectCandidateSet(candidates=candidates),
    )


def test_resolution_schema_has_no_model_generated_offsets_or_confidence() -> None:
    from app.ai.schemas import SourceTextEvidence

    assert "start_offset" not in SourceTextEvidence.model_fields
    assert "end_offset" not in SourceTextEvidence.model_fields
    assert "confidence" not in ProjectResolution.model_fields


def test_resolution_status_cardinality_is_typed() -> None:
    context = _context(2)
    project_id = context.candidates.candidates[0].project_id
    with pytest.raises(ValidationError, match="requires a signal or source excerpt"):
        ResolutionEvidence(
            project_id=project_id,
            signal_references=(),
            source_evidence=(),
            interpretation="Supporting evidence",
        )

    with pytest.raises(ValidationError, match="exactly one"):
        ProjectResolution(
            status=ResolutionStatus.MATCHED,
            project_ids=tuple(
                candidate.project_id for candidate in context.candidates.candidates
            ),
        )

    with pytest.raises(ValidationError, match="NO_PLAUSIBLE_CANDIDATE"):
        ProjectResolution(status=ResolutionStatus.NO_MATCH)


def test_no_match_contract_contains_no_selected_project() -> None:
    resolution = ProjectResolution(
        status=ResolutionStatus.NO_MATCH,
        concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
    )

    assert resolution.project_ids == ()
    assert resolution.evidence == ()
