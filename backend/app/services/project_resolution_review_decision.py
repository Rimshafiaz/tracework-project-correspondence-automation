from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.project_resolution_review_queue import (
    PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
    ProjectResolutionReviewAction,
    ProjectResolutionReviewApproval,
    ProjectResolutionReviewDecisionContext,
    ProjectResolutionReviewReplacementAssignment,
)
from app.models.correspondence_project_link import CorrespondenceProjectLink
from app.models.enums import ReviewStatus, ReviewType
from app.models.review_item import ReviewItem
from app.repositories.correspondence_project_link import (
    CorrespondenceProjectLinkRepository,
)
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.review_item import ReviewItemRepository
from app.repositories.review_item import ReviewItemStateError
from app.services.policy.project_resolution_review_handoff import (
    ProjectResolutionReviewHandoffError,
    ProjectResolutionReviewHandoffService,
)

REVIEW_RESOLVED_AUDIT_EVENT = "project_resolution_review_resolved"


class ProjectResolutionReviewDecisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectResolutionReviewDecisionResult:
    review_item: ReviewItem
    action: ProjectResolutionReviewAction
    project_links: tuple[CorrespondenceProjectLink, ...]
    created_project_link_ids: tuple[UUID, ...]
    idempotent_replay: bool


class ProjectResolutionReviewDecisionService:
    def __init__(
        self,
        *,
        session: Session,
        review_repository: ReviewItemRepository,
        lineage_repository: LineageRepository,
        project_repository: ProjectRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
    ) -> None:
        self.session = session
        self.review_repository = review_repository
        self.lineage_repository = lineage_repository
        self.project_repository = project_repository
        self.project_link_repository = project_link_repository

    def approve(
        self,
        review_item_id: UUID,
        decision: ProjectResolutionReviewApproval,
    ) -> ProjectResolutionReviewDecisionResult:
        return self._resolve(
            review_item_id=review_item_id,
            decision=decision,
            requested_action=ProjectResolutionReviewAction.APPROVE_PROPOSAL,
        )

    def assign_or_correct(
        self,
        review_item_id: UUID,
        decision: ProjectResolutionReviewReplacementAssignment,
    ) -> ProjectResolutionReviewDecisionResult:
        return self._resolve(
            review_item_id=review_item_id,
            decision=decision,
            requested_action=None,
        )

    def reject(
        self,
        review_item_id: UUID,
        decision: ProjectResolutionReviewDecisionContext,
    ) -> ProjectResolutionReviewDecisionResult:
        return self._resolve(
            review_item_id=review_item_id,
            decision=decision,
            requested_action=ProjectResolutionReviewAction.REJECT,
        )

    def _resolve(
        self,
        *,
        review_item_id: UUID,
        decision: ProjectResolutionReviewDecisionContext,
        requested_action: ProjectResolutionReviewAction | None,
    ) -> ProjectResolutionReviewDecisionResult:
        try:
            review = self.review_repository.get_for_update(review_item_id)
            if review is None:
                raise ProjectResolutionReviewDecisionError(
                    "project-resolution review item was not found"
                )
            if review.review_type is not ReviewType.PROJECT_RESOLUTION:
                raise ProjectResolutionReviewDecisionError(
                    "review item is not a project-resolution review"
                )
            transition = self.review_repository.get_state_transition(
                review.state_transition_id
            )
            if transition is None:
                raise ProjectResolutionReviewDecisionError(
                    "project-resolution review transition was not found"
                )
            if (
                transition.affected_entity_type
                != PROJECT_RESOLUTION_LINK_ENTITY_TYPE
                or transition.affected_entity_id != review.correspondence_event_id
            ):
                raise ProjectResolutionReviewDecisionError(
                    "project-resolution review transition is inconsistent"
                )
            handoff = ProjectResolutionReviewHandoffService(
                self.lineage_repository
            ).load(transition.policy_evaluation_id)
            if (
                handoff.correspondence_event_id != review.correspondence_event_id
                or handoff.proposal_id != transition.ai_proposal_id
            ):
                raise ProjectResolutionReviewDecisionError(
                    "project-resolution review lineage is inconsistent"
                )
            action, project_ids = self._requested_outcome(
                handoff=handoff,
                decision=decision,
                requested_action=requested_action,
            )
            if review.status is not ReviewStatus.PENDING:
                result = self._idempotent_result(
                    review=review,
                    action=action,
                    project_ids=project_ids,
                )
                self.session.commit()
                return result

            self._validate_projects(project_ids)
            links, created_link_ids = self._ensure_links(
                correspondence_event_id=review.correspondence_event_id,
                project_ids=project_ids,
            )
            resolved_at = datetime.now(UTC)
            if action is ProjectResolutionReviewAction.APPROVE_PROPOSAL:
                self.review_repository.mark_transition_applied(
                    transition,
                    applied_at=resolved_at,
                )
                self.review_repository.mark_approved(
                    review,
                    resolved_at=resolved_at,
                )
            elif action in {
                ProjectResolutionReviewAction.CORRECT_PROJECTS,
                ProjectResolutionReviewAction.MANUAL_ASSIGNMENT,
            }:
                self.review_repository.mark_transition_superseded(transition)
                self.review_repository.mark_corrected(
                    review,
                    correction_payload={
                        "action": action.value,
                        "selected_project_ids": [str(item) for item in project_ids],
                        "project_link_ids": [str(link.id) for link in links],
                    },
                    resolved_at=resolved_at,
                )
            else:
                self.review_repository.mark_transition_rejected(transition)
                self.review_repository.mark_rejected(
                    review,
                    resolved_at=resolved_at,
                )

            self.lineage_repository.create_audit_event(
                event_type=REVIEW_RESOLVED_AUDIT_EVENT,
                actor_type=decision.actor.actor_type,
                actor_identifier=decision.actor.actor_identifier,
                correspondence_event_id=review.correspondence_event_id,
                ai_proposal_id=handoff.proposal_id,
                policy_evaluation_id=handoff.policy_evaluation_id,
                state_transition_id=transition.id,
                review_item_id=review.id,
                details={
                    "authorization": "HUMAN_REVIEW",
                    "action": action.value,
                    "selected_project_ids": [str(item) for item in project_ids],
                    "project_link_ids": [str(link.id) for link in links],
                    "comment": decision.comment,
                },
            )
            self.session.commit()
            return ProjectResolutionReviewDecisionResult(
                review_item=review,
                action=action,
                project_links=links,
                created_project_link_ids=created_link_ids,
                idempotent_replay=False,
            )
        except (ProjectResolutionReviewHandoffError, ReviewItemStateError) as exc:
            self.session.rollback()
            raise ProjectResolutionReviewDecisionError(str(exc)) from exc
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _requested_outcome(*, handoff, decision, requested_action):
        if requested_action is ProjectResolutionReviewAction.APPROVE_PROPOSAL:
            if not handoff.selected_project_ids:
                raise ProjectResolutionReviewDecisionError(
                    "a no-match review requires manual project assignment"
                )
            return requested_action, handoff.selected_project_ids
        if requested_action is ProjectResolutionReviewAction.REJECT:
            return requested_action, ()
        if not isinstance(decision, ProjectResolutionReviewReplacementAssignment):
            raise ProjectResolutionReviewDecisionError(
                "replacement project assignment is required"
            )
        project_ids = tuple(sorted(decision.project_ids, key=str))
        if handoff.requires_manual_project_assignment:
            return ProjectResolutionReviewAction.MANUAL_ASSIGNMENT, project_ids
        if set(project_ids) == set(handoff.selected_project_ids):
            raise ProjectResolutionReviewDecisionError(
                "use approval to accept the proposed project set"
            )
        return ProjectResolutionReviewAction.CORRECT_PROJECTS, project_ids

    def _validate_projects(self, project_ids: tuple[UUID, ...]) -> None:
        missing = [
            project_id
            for project_id in project_ids
            if self.project_repository.get(project_id) is None
        ]
        if missing:
            raise ProjectResolutionReviewDecisionError(
                "one or more selected projects do not exist"
            )

    def _ensure_links(
        self,
        *,
        correspondence_event_id: UUID,
        project_ids: tuple[UUID, ...],
    ) -> tuple[tuple[CorrespondenceProjectLink, ...], tuple[UUID, ...]]:
        links = []
        created_ids = []
        for project_id in project_ids:
            link, created = self.project_link_repository.get_or_create_approved_link(
                correspondence_event_id=correspondence_event_id,
                project_id=project_id,
            )
            links.append(link)
            if created:
                created_ids.append(link.id)
        return tuple(links), tuple(created_ids)

    def _idempotent_result(
        self,
        *,
        review: ReviewItem,
        action: ProjectResolutionReviewAction,
        project_ids: tuple[UUID, ...],
    ) -> ProjectResolutionReviewDecisionResult:
        expected_status = {
            ProjectResolutionReviewAction.APPROVE_PROPOSAL: ReviewStatus.APPROVED,
            ProjectResolutionReviewAction.CORRECT_PROJECTS: ReviewStatus.CORRECTED,
            ProjectResolutionReviewAction.MANUAL_ASSIGNMENT: ReviewStatus.CORRECTED,
            ProjectResolutionReviewAction.REJECT: ReviewStatus.REJECTED,
        }[action]
        if review.status is not expected_status:
            raise ProjectResolutionReviewDecisionError(
                "review item has already been resolved differently"
            )
        if review.status is ReviewStatus.CORRECTED:
            payload = review.correction_payload or {}
            if (
                payload.get("action") != action.value
                or set(payload.get("selected_project_ids", ()))
                != {str(item) for item in project_ids}
            ):
                raise ProjectResolutionReviewDecisionError(
                    "review item has already been resolved differently"
                )
        links = []
        for project_id in project_ids:
            link = self.project_link_repository.get_approved_link(
                correspondence_event_id=review.correspondence_event_id,
                project_id=project_id,
            )
            if link is None:
                raise ProjectResolutionReviewDecisionError(
                    "resolved review is missing its authoritative project link"
                )
            links.append(link)
        return ProjectResolutionReviewDecisionResult(
            review_item=review,
            action=action,
            project_links=tuple(links),
            created_project_link_ids=(),
            idempotent_replay=True,
        )
