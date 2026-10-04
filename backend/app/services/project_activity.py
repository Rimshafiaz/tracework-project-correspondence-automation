from uuid import UUID, uuid5

from pydantic import ValidationError

from app.contracts.evidence_lineage import LineageAttribution
from app.contracts.project_activity import ProjectActivity, ProjectActivityEvent, ProjectActivityType
from app.contracts.requirement_policy import RequirementTransitionEffect
from app.contracts.requirement_reconciliation import (
    RequirementContextSnapshotError,
    reconstruct_requirement_context_snapshot,
)
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.services.policy.project_identity_authorization import AUTO_LINKED_AUDIT_EVENT
from app.services.policy.requirement_authorization import REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT
from app.services.project_resolution_review_creation import REVIEW_CREATED_AUDIT_EVENT
from app.services.project_resolution_review_decision import REVIEW_RESOLVED_AUDIT_EVENT
from app.services.requirement_review_creation import REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT

REQUIREMENT_RECONCILIATION_PROPOSED_AUDIT_EVENT = "requirement_reconciliation_proposed"


class ProjectActivityError(RuntimeError):
    pass


class ProjectActivityService:
    def __init__(
        self,
        *,
        project_repository: ProjectRepository,
        lineage_repository: LineageRepository,
    ) -> None:
        self.project_repository = project_repository
        self.lineage_repository = lineage_repository

    def load(self, project_id: UUID) -> ProjectActivity:
        if self.project_repository.get(project_id) is None:
            raise ProjectActivityError("project was not found")

        events = []
        for audit in self.lineage_repository.list_project_activity_audit_events(
            project_id
        ):
            events.extend(self._business_events(project_id, audit))
        events.sort(key=lambda item: (item.occurred_at, str(item.event_id)))
        return ProjectActivity(project_id=project_id, events=tuple(events))

    def _business_events(self, project_id: UUID, audit) -> tuple[ProjectActivityEvent, ...]:
        if audit.event_type == AUTO_LINKED_AUDIT_EVENT:
            if audit.project_id != project_id:
                return ()
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.CORRESPONDENCE_LINKED,
                    "Correspondence linked to this project automatically.",
                ),
            )
        if audit.event_type == REVIEW_CREATED_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.PROJECT_RESOLUTION_REVIEW_CREATED,
                    "Project-resolution review created.",
                ),
            )
        if audit.event_type == REVIEW_RESOLVED_AUDIT_EVENT:
            selected_ids = self._uuid_set(audit.details.get("selected_project_ids", ()))
            linked = project_id in selected_ids
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.PROJECT_RESOLUTION_REVIEW_RESOLVED,
                    (
                        "Correspondence linked to this project after human review."
                        if linked
                        else "Project-resolution review resolved without linking this project."
                    ),
                ),
            )
        if audit.project_id != project_id:
            return ()
        if audit.event_type == REQUIREMENT_RECONCILIATION_PROPOSED_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REQUIREMENT_CHANGE_PROPOSED,
                    "Requirement changes proposed from correspondence.",
                ),
            )
        if audit.event_type == REQUIREMENT_REVIEW_CREATED_AUDIT_EVENT:
            review_type = audit.details.get("review_type")
            summary = (
                "New requirement proposal sent for human review."
                if review_type == "NEW_REQUIREMENT"
                else "Requirement changes sent for human review."
            )
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REQUIREMENT_REVIEW_CREATED,
                    summary,
                ),
            )
        if audit.event_type == REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT:
            return self._requirement_changes(project_id, audit)
        return ()

    def _requirement_changes(self, project_id: UUID, audit) -> tuple[ProjectActivityEvent, ...]:
        if audit.state_transition_id is None:
            raise ProjectActivityError("requirement activity is missing its transition")
        transition = self.lineage_repository.get_state_transition_by_id(
            audit.state_transition_id
        )
        if transition is None:
            raise ProjectActivityError("requirement activity transition was not found")
        try:
            proposal = self.lineage_repository.get_proposal(audit.ai_proposal_id)
            if proposal is None:
                raise ProjectActivityError(
                    "requirement activity proposal was not found"
                )
            snapshot = reconstruct_requirement_context_snapshot(
                proposal.input_metadata
            )
            if snapshot.project_id != project_id:
                raise ProjectActivityError(
                    "requirement activity proposal belongs to another project"
                )
            requirement_names = {
                item.requirement_id: item.name for item in snapshot.requirements
            }
            effects = tuple(
                RequirementTransitionEffect.model_validate(item)
                for item in transition.requirement_effects
            )
        except (RequirementContextSnapshotError, ValidationError) as exc:
            raise ProjectActivityError(
                "requirement activity transition is invalid"
            ) from exc

        events = []
        for effect in effects:
            requirement_name = requirement_names.get(effect.requirement_id)
            if requirement_name is None:
                raise ProjectActivityError("requirement activity reference is invalid")
            events.append(
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REQUIREMENT_CHANGE_APPLIED,
                    (
                        f'Requirement "{requirement_name}" moved '
                        f"{effect.current_state.value} → {effect.proposed_state.value}."
                    ),
                    event_id=uuid5(audit.id, str(effect.requirement_id)),
                    requirement_id=effect.requirement_id,
                )
            )
        return tuple(events)

    @staticmethod
    def _event(
        audit,
        project_id: UUID,
        event_type: ProjectActivityType,
        summary: str,
        *,
        event_id: UUID | None = None,
        requirement_id: UUID | None = None,
    ) -> ProjectActivityEvent:
        human = audit.actor_type != "system"
        return ProjectActivityEvent(
            event_id=event_id or audit.id,
            event_type=event_type,
            occurred_at=audit.occurred_at,
            project_id=project_id,
            correspondence_event_id=audit.correspondence_event_id,
            requirement_id=requirement_id,
            summary=summary,
            attribution=(
                LineageAttribution.HUMAN
                if human
                else LineageAttribution.AUTOMATIC
            ),
            authenticated_operator_subject=(
                audit.actor_identifier
                if audit.actor_type == "authenticated_operator"
                else None
            ),
            operator_supplied_actor_label=(
                audit.actor_identifier
                if audit.actor_type == "operator_supplied"
                else None
            ),
            proposal_id=audit.ai_proposal_id,
            policy_evaluation_id=audit.policy_evaluation_id,
            state_transition_id=audit.state_transition_id,
            review_item_id=audit.review_item_id,
        )

    @staticmethod
    def _uuid_set(values) -> set[UUID]:
        try:
            return {UUID(value) for value in values}
        except (TypeError, ValueError) as exc:
            raise ProjectActivityError(
                "project-resolution activity contains invalid project references"
            ) from exc
