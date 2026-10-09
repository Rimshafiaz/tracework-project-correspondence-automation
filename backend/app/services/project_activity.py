from uuid import UUID, uuid5

from pydantic import ValidationError
from app.ai.requirement_schemas import RequirementCorrectionProposal, RequirementCorrectionKind

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
from app.services.requirement_review_decision import (
    REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT,
    REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT,
)
from app.services.document_filing import DOCUMENT_FILED_AUDIT_EVENT
from app.services.document_revision import (
    DOCUMENT_REVISION_DUPLICATE_RECORDED,
    DOCUMENT_REVISION_RETAINED_HISTORICAL,
    DOCUMENT_REVISION_REVIEW_CREATED,
    DOCUMENT_REVISION_SELECTED_CURRENT,
)
from app.services.follow_up_due import FOLLOW_UP_BECAME_DUE_AUDIT_EVENT
from app.services.follow_up_lifecycle import FOLLOW_UP_CANCELLED_AUDIT_EVENT
from app.services.reply_draft_review import REPLY_DRAFT_APPROVED_AUDIT_EVENT
from app.services.reply_draft_send import (
    FOLLOW_UP_COMPLETED_AUDIT_EVENT,
    REPLY_SENT_AUDIT_EVENT,
)

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
        if audit.event_type == REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT:
            transition = self.lineage_repository.get_state_transition_by_id(audit.state_transition_id)
            if transition is not None and isinstance(transition.proposed_state, dict) and transition.proposed_state.get("correction_candidates"):
                return self._correction_changes(project_id, audit, transition)
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REQUIREMENT_REVIEW_APPROVED,
                    "Requirement review approved and applied.",
                    requirement_id=audit.requirement_id,
                ),
            )
        if audit.event_type == REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REQUIREMENT_REVIEW_REJECTED,
                    "Requirement review rejected.",
                    requirement_id=audit.requirement_id,
                ),
            )
        if audit.event_type == REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT:
            return self._requirement_changes(project_id, audit)
        if audit.event_type == DOCUMENT_FILED_AUDIT_EVENT:
            filename = audit.details.get("filename")
            summary = (
                f'Document "{filename}" filed to Google Drive.'
                if isinstance(filename, str) and filename.strip()
                else "Document filed to Google Drive."
            )
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.DOCUMENT_FILED,
                    summary,
                    expose_transition=False,
                ),
            )
        if audit.event_type == FOLLOW_UP_BECAME_DUE_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.FOLLOW_UP_BECAME_DUE,
                    "Follow-up became due.",
                    requirement_id=audit.requirement_id,
                ),
            )
        if audit.event_type == REPLY_DRAFT_APPROVED_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REPLY_DRAFT_APPROVED,
                    "Reply draft approved.",
                    requirement_id=audit.requirement_id,
                ),
            )
        if audit.event_type == FOLLOW_UP_CANCELLED_AUDIT_EVENT and audit.details.get("cancellation_reason") == "REQUIREMENT_RETRACTED":
            return (self._event(audit, project_id, ProjectActivityType.FOLLOW_UP_CANCELLED,
                "Active follow-up cancelled because the requirement was retracted.", requirement_id=audit.requirement_id),)
        if audit.event_type == REPLY_SENT_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.REPLY_SENT,
                    "Reply sent.",
                    requirement_id=audit.requirement_id,
                ),
            )
        if audit.event_type == FOLLOW_UP_COMPLETED_AUDIT_EVENT:
            return (
                self._event(
                    audit,
                    project_id,
                    ProjectActivityType.FOLLOW_UP_COMPLETED,
                    "Follow-up completed after reply delivery.",
                    requirement_id=audit.requirement_id,
                ),
            )
        revision_activity = {
            DOCUMENT_REVISION_SELECTED_CURRENT: (
                ProjectActivityType.DOCUMENT_REVISION_SELECTED_CURRENT,
                "Document selected as the current revision.",
            ),
            DOCUMENT_REVISION_RETAINED_HISTORICAL: (
                ProjectActivityType.DOCUMENT_REVISION_RETAINED_HISTORICAL,
                "Document retained as a historical revision.",
            ),
            DOCUMENT_REVISION_DUPLICATE_RECORDED: (
                ProjectActivityType.DOCUMENT_REVISION_DUPLICATE_RECORDED,
                "Duplicate revision submission retained historically.",
            ),
            DOCUMENT_REVISION_REVIEW_CREATED: (
                ProjectActivityType.DOCUMENT_REVISION_REVIEW_CREATED,
                "Document revision sent for inspection.",
            ),
        }.get(audit.event_type)
        if revision_activity is not None:
            event_type, summary = revision_activity
            return (
                self._event(
                    audit,
                    project_id,
                    event_type,
                    summary,
                    expose_transition=False,
                ),
            )
        return ()

    def _correction_changes(self, project_id, audit, transition):
        proposal = self.lineage_repository.get_proposal(audit.ai_proposal_id)
        if proposal is None:
            raise ProjectActivityError("correction activity proposal was not found")
        try:
            snapshot = reconstruct_requirement_context_snapshot(proposal.input_metadata)
            corrections = tuple(RequirementCorrectionProposal.model_validate(item)
                for item in transition.proposed_state["correction_candidates"])
        except (RequirementContextSnapshotError, ValidationError) as exc:
            raise ProjectActivityError("correction activity is invalid") from exc
        if snapshot.project_id != project_id:
            raise ProjectActivityError("correction activity belongs to another project")
        names = {item.requirement_id: item.name for item in snapshot.requirements}
        events = []
        for correction in corrections:
            name = names.get(correction.requirement_id)
            if name is None:
                raise ProjectActivityError("correction activity requirement was not found")
            if correction.kind is RequirementCorrectionKind.RETRACTION:
                summary = f'Requirement "{name}" retracted after later correspondence; it is no longer applicable.'
            else:
                changes = []
                if correction.proposed_expected_date is not None:
                    changes.append(f"expected date changed from {correction.previous_expected_date or 'not set'} to {correction.proposed_expected_date}")
                if correction.proposed_state is not None:
                    changes.append(f"state changed from {correction.previous_state.value.lower()} to {correction.proposed_state.value.lower()}")
                summary = f'Requirement "{name}": {"; ".join(changes)} after later correspondence.'
            events.append(self._event(audit, project_id, ProjectActivityType.REQUIREMENT_REVIEW_APPROVED, summary,
                event_id=uuid5(audit.id, str(correction.requirement_id)), requirement_id=correction.requirement_id))
        return tuple(events)

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
        expose_transition: bool = True,
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
            state_transition_id=(
                audit.state_transition_id if expose_transition else None
            ),
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
