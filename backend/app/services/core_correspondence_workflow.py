from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ai_proposal import AIProposal
from app.models.enums import (
    CorrespondenceProcessingState,
    PolicyDecision,
    ProposalType,
    ReviewStatus,
)
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.lineage import LineageRepository
from app.services.project_resolution import ProjectResolutionService
from app.services.project_resolution_context import ProjectResolutionContextService
from app.services.project_resolution_workflow import ProjectResolutionWorkflowService
from app.services.requirement_policy_workflow import RequirementPolicyWorkflowService
from app.services.requirement_reconciliation import RequirementReconciliationService
from app.services.requirement_reconciliation_context import RequirementReconciliationContextService


class CoreWorkflowStatus(StrEnum):
    COMPLETED = "COMPLETED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    ALREADY_PROCESSING = "ALREADY_PROCESSING"


@dataclass(frozen=True)
class RequirementWorkflowOutcome:
    project_id: UUID
    project_link_id: UUID
    proposal_id: UUID
    policy_evaluation_id: UUID
    decision: PolicyDecision
    state_transition_id: UUID | None
    review_item_id: UUID | None


@dataclass(frozen=True)
class CoreCorrespondenceWorkflowResult:
    correspondence_event_id: UUID
    status: CoreWorkflowStatus
    project_proposal_id: UUID | None = None
    project_policy_evaluation_id: UUID | None = None
    project_decision: PolicyDecision | None = None
    project_link_ids: tuple[UUID, ...] = ()
    project_review_item_id: UUID | None = None
    requirement_outcomes: tuple[RequirementWorkflowOutcome, ...] = ()


class CoreCorrespondenceWorkflowError(RuntimeError):
    pass


class CoreCorrespondenceWorkflowService:
    """Coordinates the existing M7-M12 services for one persisted event."""

    def __init__(
        self,
        *,
        session: Session,
        correspondence_repository: CorrespondenceEventRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
        lineage_repository: LineageRepository,
        project_context_service: ProjectResolutionContextService,
        project_resolution_service: ProjectResolutionService,
        project_workflow_service: ProjectResolutionWorkflowService,
        requirement_context_service: RequirementReconciliationContextService,
        requirement_reconciliation_service: RequirementReconciliationService,
        requirement_workflow_service: RequirementPolicyWorkflowService,
    ) -> None:
        self.session = session
        self.correspondence_repository = correspondence_repository
        self.project_link_repository = project_link_repository
        self.lineage_repository = lineage_repository
        self.project_context_service = project_context_service
        self.project_resolution_service = project_resolution_service
        self.project_workflow_service = project_workflow_service
        self.requirement_context_service = requirement_context_service
        self.requirement_reconciliation_service = requirement_reconciliation_service
        self.requirement_workflow_service = requirement_workflow_service

    async def process(self, correspondence_event_id: UUID) -> CoreCorrespondenceWorkflowResult:
        event = self.correspondence_repository.get_for_update(correspondence_event_id)
        if event is None:
            raise CoreCorrespondenceWorkflowError("correspondence event was not found")
        if event.processing_state is CorrespondenceProcessingState.COMPLETED:
            self.session.rollback()
            return CoreCorrespondenceWorkflowResult(
                correspondence_event_id=correspondence_event_id,
                status=CoreWorkflowStatus.ALREADY_COMPLETED,
            )
        if event.processing_state is CorrespondenceProcessingState.PROCESSING:
            self.session.rollback()
            return CoreCorrespondenceWorkflowResult(
                correspondence_event_id=correspondence_event_id,
                status=CoreWorkflowStatus.ALREADY_PROCESSING,
            )

        self.correspondence_repository.update_processing_state(
            event,
            state=CorrespondenceProcessingState.PROCESSING,
            failure_metadata=None,
        )
        self.session.commit()

        stage = "project_resolution"
        try:
            project_proposal = self._project_proposal(correspondence_event_id)
            if project_proposal is None:
                project_context = self.project_context_service.build(
                    correspondence_event_id
                )
                project_proposal = (
                    await self.project_resolution_service.resolve(project_context)
                ).proposal
                self.session.commit()

            stage = "project_policy"
            project_result = self.project_workflow_service.process(
                project_proposal.id
            )
            project_decision = project_result.authorization.evaluation.decision
            common = {
                "correspondence_event_id": correspondence_event_id,
                "project_proposal_id": project_proposal.id,
                "project_policy_evaluation_id": (
                    project_result.authorization.evaluation.id
                ),
                "project_decision": project_decision,
                "project_link_ids": tuple(
                    link.id for link in project_result.authorization.project_links
                ),
                "project_review_item_id": (
                    project_result.review_item.id
                    if project_result.review_item is not None
                    else None
                ),
            }
            project_links = project_result.authorization.project_links
            if project_decision is PolicyDecision.REVIEW_REQUIRED:
                review = project_result.review_item
                if review is None or review.status is ReviewStatus.PENDING:
                    self._set_state(
                        correspondence_event_id,
                        CorrespondenceProcessingState.PENDING,
                    )
                    return CoreCorrespondenceWorkflowResult(
                        status=CoreWorkflowStatus.REVIEW_REQUIRED,
                        **common,
                    )
                if review.status is ReviewStatus.REJECTED:
                    self._complete(correspondence_event_id)
                    return CoreCorrespondenceWorkflowResult(
                        status=CoreWorkflowStatus.REJECTED,
                        **common,
                    )
                project_links = self._approved_links(correspondence_event_id)
                if not project_links:
                    raise CoreCorrespondenceWorkflowError(
                        "resolved project review has no authoritative project link"
                    )
                common["project_link_ids"] = tuple(
                    link.id for link in project_links
                )
            if project_decision is PolicyDecision.REJECT_PROPOSAL:
                self._complete(correspondence_event_id)
                return CoreCorrespondenceWorkflowResult(
                    status=CoreWorkflowStatus.REJECTED,
                    **common,
                )
            if not project_links:
                raise CoreCorrespondenceWorkflowError(
                    "automatic project authorization produced no project link"
                )

            requirement_outcomes = []
            for link in project_links:
                stage = f"requirement_reconciliation:{link.project_id}"
                requirement_proposal = self._requirement_proposal(
                    correspondence_event_id=correspondence_event_id,
                    project_id=link.project_id,
                )
                if requirement_proposal is None:
                    requirement_context = self.requirement_context_service.build(link.id)
                    requirement_proposal = (
                        await self.requirement_reconciliation_service.reconcile(
                            requirement_context
                        )
                    ).proposal
                    self.session.commit()

                stage = f"requirement_policy:{link.project_id}"
                requirement_result = self.requirement_workflow_service.process(
                    requirement_proposal.id
                )
                requirement_outcomes.append(
                    RequirementWorkflowOutcome(
                        project_id=link.project_id,
                        project_link_id=link.id,
                        proposal_id=requirement_proposal.id,
                        policy_evaluation_id=(
                            requirement_result.authorization.evaluation.id
                        ),
                        decision=(
                            requirement_result.authorization.evaluation.decision
                        ),
                        state_transition_id=(
                            requirement_result.authorization.transition.id
                            if requirement_result.authorization.transition is not None
                            else None
                        ),
                        review_item_id=(
                            requirement_result.review.review_item.id
                            if requirement_result.review is not None
                            else None
                        ),
                    )
                )

            self._complete(correspondence_event_id)
            return CoreCorrespondenceWorkflowResult(
                status=CoreWorkflowStatus.COMPLETED,
                requirement_outcomes=tuple(requirement_outcomes),
                **common,
            )
        except Exception as exc:
            self.session.rollback()
            failed_event = self.correspondence_repository.get_for_update(
                correspondence_event_id
            )
            if failed_event is not None:
                self.correspondence_repository.update_processing_state(
                    failed_event,
                    state=CorrespondenceProcessingState.RETRYABLE_FAILURE,
                    failure_metadata={
                        "stage": stage,
                        "error_type": type(exc).__name__,
                    },
                )
                self.session.commit()
            raise

    def _project_proposal(self, correspondence_event_id: UUID) -> AIProposal | None:
        proposals = self.lineage_repository.list_proposals_for_event(
            correspondence_event_id=correspondence_event_id,
            proposal_type=ProposalType.PROJECT_RESOLUTION,
        )
        return proposals[0] if proposals else None

    def _requirement_proposal(
        self,
        *,
        correspondence_event_id: UUID,
        project_id: UUID,
    ) -> AIProposal | None:
        proposals = self.lineage_repository.list_proposals_for_event(
            correspondence_event_id=correspondence_event_id,
            proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        )
        expected_project_id = str(project_id)
        return next(
            (
                proposal
                for proposal in proposals
                if (proposal.input_metadata or {}).get("project_id")
                == expected_project_id
            ),
            None,
        )

    def _complete(self, correspondence_event_id: UUID) -> None:
        self._set_state(
            correspondence_event_id,
            CorrespondenceProcessingState.COMPLETED,
        )

    def _set_state(
        self,
        correspondence_event_id: UUID,
        state: CorrespondenceProcessingState,
    ) -> None:
        event = self.correspondence_repository.get_for_update(correspondence_event_id)
        if event is None:
            raise CoreCorrespondenceWorkflowError(
                "correspondence event disappeared during processing"
            )
        self.correspondence_repository.update_processing_state(
            event,
            state=state,
            failure_metadata=None,
        )
        self.session.commit()

    def _approved_links(self, correspondence_event_id: UUID):
        project_ids = self.project_link_repository.list_approved_project_ids_for_event(
            correspondence_event_id
        )
        links = []
        for project_id in project_ids:
            link = self.project_link_repository.get_approved_link(
                correspondence_event_id=correspondence_event_id,
                project_id=project_id,
            )
            if link is not None:
                links.append(link)
        return tuple(links)
