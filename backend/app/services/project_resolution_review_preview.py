from collections.abc import Sequence
from uuid import UUID

from app.contracts.project_resolution_review import ProjectResolutionReviewHandoff
from app.contracts.project_resolution_review_queue import ProjectResolutionReviewPreview
from app.models.enums import TransitionDisposition


def build_project_resolution_review_preview(
    *,
    handoff: ProjectResolutionReviewHandoff,
    current_project_ids: Sequence[UUID] = (),
) -> ProjectResolutionReviewPreview:
    return ProjectResolutionReviewPreview(
        correspondence_event_id=handoff.correspondence_event_id,
        resolver_status=handoff.resolution.status,
        current_project_ids=tuple(current_project_ids),
        proposed_project_ids=handoff.selected_project_ids,
        alternative_project_ids=handoff.alternative_project_ids,
        valid_evidence_ids=handoff.valid_evidence_ids,
        invalidated_evidence_ids=handoff.invalidated_evidence_ids,
        policy=handoff.policy,
        disposition=TransitionDisposition.REVIEW,
        requires_manual_project_assignment=(
            handoff.requires_manual_project_assignment
        ),
    )
