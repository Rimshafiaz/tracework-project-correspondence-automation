from collections.abc import Sequence
from uuid import UUID

from app.contracts.project_resolution_review import ProjectResolutionReviewHandoff
from app.contracts.project_resolution_review_queue import ProjectLinkAuthorizationPreview, ProjectResolutionReviewPreview
from app.contracts.transition_preview import PolicyEvaluationSnapshot
from app.models.enums import TransitionDisposition
from app.models.policy_evaluation import PolicyEvaluation


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


def build_project_link_authorization_preview(
    *,
    correspondence_event_id: UUID,
    current_project_ids: Sequence[UUID],
    authorized_project_ids: Sequence[UUID],
    evidence_ids: Sequence[UUID],
    evaluation: PolicyEvaluation,
) -> ProjectLinkAuthorizationPreview | None:
    current = tuple(dict.fromkeys(current_project_ids))
    authorized = tuple(dict.fromkeys(authorized_project_ids))
    current_set = set(current)
    added = tuple(project_id for project_id in authorized if project_id not in current_set)
    if not added:
        return None
    result = (*current, *added)
    return ProjectLinkAuthorizationPreview(
        correspondence_event_id=correspondence_event_id,
        current_project_ids=current,
        authorized_project_ids=authorized,
        added_project_ids=added,
        result_project_ids=result,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        policy=PolicyEvaluationSnapshot(
            id=evaluation.id,
            policy_version=evaluation.policy_version,
            decision=evaluation.decision,
            triggered_rule_ids=tuple(evaluation.triggered_rule_ids),
            reasons=tuple(evaluation.reasons),
        ),
    )
