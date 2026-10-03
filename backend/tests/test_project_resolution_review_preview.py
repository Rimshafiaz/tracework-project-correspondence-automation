from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.schemas import ProjectResolution, ResolutionConcern, ResolutionStatus
from app.contracts.project_candidate import (
    CandidateSignalSource,
    CandidateSignalType,
    ProjectCandidate,
    ProjectCandidateSet,
    ProjectCandidateSignal,
)
from app.contracts.project_resolution_review import ProjectResolutionReviewHandoff
from app.contracts.transition_preview import PolicyEvaluationSnapshot
from app.models.enums import PolicyDecision, ProjectStatus, TransitionDisposition
from app.services.project_resolution_review_preview import (
    build_project_link_authorization_preview,
    build_project_resolution_review_preview,
)


def _candidate(name: str) -> ProjectCandidate:
    project_id = uuid4()
    return ProjectCandidate(
        project_id=project_id,
        project_code=f"CODE-{str(project_id)[:8]}",
        project_name=name,
        project_status=ProjectStatus.ACTIVE,
        signals=(
            ProjectCandidateSignal(
                signal_type=CandidateSignalType.NORMALIZED_NAME,
                matched_value=name.casefold(),
                source=CandidateSignalSource.CORRESPONDENCE_EVENT,
                exact=True,
            ),
        ),
    )


def _handoff(
    *,
    status: ResolutionStatus,
    candidates: tuple[ProjectCandidate, ...] = (),
    selected_project_ids=(),
    valid_evidence_ids=(),
    invalidated_evidence_ids=(),
    decision: PolicyDecision = PolicyDecision.REVIEW_REQUIRED,
) -> ProjectResolutionReviewHandoff:
    concerns = (
        (ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,)
        if status is ResolutionStatus.NO_MATCH
        else (ResolutionConcern.INSUFFICIENT_EVIDENCE,)
    )
    resolution_values = {
        "status": status,
        "project_ids": selected_project_ids,
        "concerns": concerns,
    }
    if selected_project_ids:
        resolution_values["evidence"] = tuple(
            {
                "project_id": project_id,
                "signal_references": (
                    {
                        "project_id": project_id,
                        "signal_type": CandidateSignalType.NORMALIZED_NAME,
                        "matched_value": next(
                            candidate.signals[0].matched_value
                            for candidate in candidates
                            if candidate.project_id == project_id
                        ),
                        "source": CandidateSignalSource.CORRESPONDENCE_EVENT,
                    },
                ),
                "interpretation": "The correspondence plausibly names this project.",
            }
            for project_id in selected_project_ids
        )
    evidence_ids = (*valid_evidence_ids, *invalidated_evidence_ids)
    return ProjectResolutionReviewHandoff(
        correspondence_event_id=uuid4(),
        proposal_id=uuid4(),
        policy_evaluation_id=uuid4(),
        candidate_set=ProjectCandidateSet(candidates=candidates),
        resolution=ProjectResolution.model_validate(resolution_values),
        policy=PolicyEvaluationSnapshot(
            id=uuid4(),
            policy_version="project-identity/1",
            decision=decision,
            triggered_rule_ids=("PID-101-RESOLVER-REVIEW-REQUIRED",),
            reasons=("Human review is required.",),
        ),
        proposal_evidence_ids=evidence_ids,
        valid_evidence_ids=valid_evidence_ids,
        invalidated_evidence_ids=invalidated_evidence_ids,
    )


def test_preview_derives_current_proposed_alternative_and_evidence_state() -> None:
    selected = _candidate("Selected")
    alternative = _candidate("Alternative")
    current_project_id = uuid4()
    valid_evidence_id = uuid4()
    invalidated_evidence_id = uuid4()
    handoff = _handoff(
        status=ResolutionStatus.REVIEW_REQUIRED,
        candidates=(selected, alternative),
        selected_project_ids=(selected.project_id,),
        valid_evidence_ids=(valid_evidence_id,),
        invalidated_evidence_ids=(invalidated_evidence_id,),
    )

    preview = build_project_resolution_review_preview(
        handoff=handoff,
        current_project_ids=(current_project_id,),
    )

    assert preview.current_project_ids == (current_project_id,)
    assert preview.proposed_project_ids == (selected.project_id,)
    assert preview.alternative_project_ids == (alternative.project_id,)
    assert preview.valid_evidence_ids == (valid_evidence_id,)
    assert preview.invalidated_evidence_ids == (invalidated_evidence_id,)
    assert preview.policy.reasons == ("Human review is required.",)
    assert preview.disposition is TransitionDisposition.REVIEW
    assert preview.requires_manual_project_assignment is False


def test_no_match_preview_requires_no_evidence_or_placeholder_project() -> None:
    handoff = _handoff(status=ResolutionStatus.NO_MATCH)

    preview = build_project_resolution_review_preview(handoff=handoff)

    assert preview.proposed_project_ids == ()
    assert preview.alternative_project_ids == ()
    assert preview.valid_evidence_ids == ()
    assert preview.invalidated_evidence_ids == ()
    assert preview.requires_manual_project_assignment is True


def test_preview_is_deterministic_for_the_same_handoff() -> None:
    handoff = _handoff(status=ResolutionStatus.NO_MATCH)

    assert build_project_resolution_review_preview(
        handoff=handoff
    ) == build_project_resolution_review_preview(handoff=handoff)


def test_preview_rejects_non_review_policy() -> None:
    handoff = _handoff(
        status=ResolutionStatus.NO_MATCH,
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
    )

    with pytest.raises(ValidationError, match="review-required"):
        build_project_resolution_review_preview(handoff=handoff)


def test_auto_preview_separates_existing_links_from_actual_additions() -> None:
    existing = uuid4()
    added = uuid4()
    evaluation = SimpleNamespace(
        id=uuid4(),
        policy_version="project-identity/1",
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=["PID-302-AUTO-ELIGIBLE"],
        reasons=["Objective identity signals permit automatic linking."],
    )

    preview = build_project_link_authorization_preview(
        correspondence_event_id=uuid4(),
        current_project_ids=(existing,),
        authorized_project_ids=(existing, added),
        evidence_ids=(uuid4(),),
        evaluation=evaluation,
    )

    assert preview.current_project_ids == (existing,)
    assert preview.authorized_project_ids == (existing, added)
    assert preview.added_project_ids == (added,)
    assert preview.result_project_ids == (existing, added)


def test_auto_preview_returns_none_when_every_authorized_link_exists() -> None:
    existing = uuid4()
    evaluation = SimpleNamespace(
        id=uuid4(),
        policy_version="project-identity/1",
        decision=PolicyDecision.ALLOW_AUTO_ACTION,
        triggered_rule_ids=["PID-302-AUTO-ELIGIBLE"],
        reasons=["Objective identity signals permit automatic linking."],
    )

    assert build_project_link_authorization_preview(
        correspondence_event_id=uuid4(),
        current_project_ids=(existing,),
        authorized_project_ids=(existing,),
        evidence_ids=(),
        evaluation=evaluation,
    ) is None
