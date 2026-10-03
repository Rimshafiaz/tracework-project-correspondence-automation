from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.requirement_policy import RequirementPolicyResult
from app.models.ai_proposal import AIProposal
from app.models.enums import PolicyDecision, TransitionDisposition, TransitionStatus
from app.models.policy_evaluation import PolicyEvaluation
from app.models.state_transition import StateTransition
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.services.policy.requirement import evaluate_requirement_policy, reject_requirement_policy_context_failure
from app.services.policy.requirement_context import RequirementPolicyContextError, RequirementPolicyContextService
from app.services.policy.requirement_persistence import REQUIREMENT_RECONCILIATION_ENTITY_TYPE, persist_requirement_policy_result, persist_requirement_transition_preview
from app.services.policy.requirement_rules import REQUIREMENT_POLICY_VERSION

REQUIREMENT_POLICY_EVALUATED_AUDIT_EVENT = "requirement_policy_evaluated"
REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT = "requirement_policy_auto_applied"


class RequirementPolicyAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequirementPolicyAuthorizationResult:
    evaluation: PolicyEvaluation
    transition: StateTransition | None
    policy_evaluation_created: bool
    transition_created: bool
    applied_requirement_ids: tuple[UUID, ...]


class RequirementPolicyAuthorizationService:
    def __init__(
        self,
        *,
        session: Session,
        context_service: RequirementPolicyContextService,
        lineage_repository: LineageRepository,
        requirement_repository: RequirementRepository,
    ) -> None:
        self.session = session
        self.context_service = context_service
        self.lineage_repository = lineage_repository
        self.requirement_repository = requirement_repository

    def authorize(self, proposal_id: UUID) -> RequirementPolicyAuthorizationResult:
        try:
            proposal = self.lineage_repository.get_proposal_for_update(proposal_id)
            if proposal is None:
                raise RequirementPolicyAuthorizationError(
                    "requirement-reconciliation proposal was not found"
                )

            existing_evaluation = self.lineage_repository.get_policy_evaluation(
                ai_proposal_id=proposal.id,
                policy_version=REQUIREMENT_POLICY_VERSION,
            )
            existing_transition = self._get_transition(
                existing_evaluation,
                proposal.id,
            )
            if (
                existing_transition is not None
                and existing_transition.status is TransitionStatus.APPLIED
            ):
                self.session.commit()
                return RequirementPolicyAuthorizationResult(
                    evaluation=existing_evaluation,
                    transition=existing_transition,
                    policy_evaluation_created=False,
                    transition_created=False,
                    applied_requirement_ids=(),
                )

            try:
                context = self.context_service.build(
                    proposal,
                    lock_current_requirements=True,
                )
            except RequirementPolicyContextError as exc:
                result = reject_requirement_policy_context_failure(
                    proposal_id=proposal.id,
                    rule=exc.rule,
                )
                persisted_policy = persist_requirement_policy_result(
                    result,
                    self.lineage_repository,
                )
                self._ensure_policy_audit(
                    proposal=proposal,
                    evaluation=persisted_policy.evaluation,
                    result=result,
                    project_id=None,
                )
                self.session.commit()
                return RequirementPolicyAuthorizationResult(
                    evaluation=persisted_policy.evaluation,
                    transition=None,
                    policy_evaluation_created=persisted_policy.created,
                    transition_created=False,
                    applied_requirement_ids=(),
                )

            result = evaluate_requirement_policy(context)
            persisted_policy = persist_requirement_policy_result(
                result,
                self.lineage_repository,
            )
            persisted_transition = persist_requirement_transition_preview(
                context=context,
                result=result,
                evaluation=persisted_policy.evaluation,
                repository=self.lineage_repository,
            )
            transition = persisted_transition.transition
            self._ensure_policy_audit(
                proposal=proposal,
                evaluation=persisted_policy.evaluation,
                result=result,
                project_id=context.m11_snapshot.project_id,
            )

            applied_ids: tuple[UUID, ...] = ()
            if result.decision is PolicyDecision.ALLOW_AUTO_ACTION and transition:
                applied_ids = self._apply_authorized_effects(
                    proposal=proposal,
                    evaluation=persisted_policy.evaluation,
                    transition=transition,
                    result=result,
                    project_id=context.m11_snapshot.project_id,
                )
            elif result.decision is PolicyDecision.REJECT_PROPOSAL and transition:
                self.lineage_repository.mark_transition_rejected(transition)

            self.session.commit()
            return RequirementPolicyAuthorizationResult(
                evaluation=persisted_policy.evaluation,
                transition=transition,
                policy_evaluation_created=persisted_policy.created,
                transition_created=persisted_transition.created,
                applied_requirement_ids=applied_ids,
            )
        except Exception:
            self.session.rollback()
            raise

    def _apply_authorized_effects(
        self,
        *,
        proposal: AIProposal,
        evaluation: PolicyEvaluation,
        transition: StateTransition,
        result: RequirementPolicyResult,
        project_id: UUID,
    ) -> tuple[UUID, ...]:
        if transition.disposition is not TransitionDisposition.AUTO_APPLY:
            raise RequirementPolicyAuthorizationError(
                "automatic policy decision requires an AUTO_APPLY transition"
            )
        if transition.status is TransitionStatus.APPLIED:
            return ()
        if transition.status is not TransitionStatus.PREVIEWED:
            raise RequirementPolicyAuthorizationError(
                "automatic requirement transition is no longer applicable"
            )

        applied_ids = []
        for effect in result.requirement_effects:
            if effect.decision is not PolicyDecision.ALLOW_AUTO_ACTION:
                raise RequirementPolicyAuthorizationError(
                    "automatic bundle contains a non-automatic requirement effect"
                )
            requirement = self.requirement_repository.get_for_update(
                effect.requirement_id
            )
            if (
                requirement is None
                or requirement.project_id != project_id
                or requirement.state is not effect.current_state
                or requirement.expected_date != effect.current_expected_date
            ):
                raise RequirementPolicyAuthorizationError(
                    "requirement changed after policy evaluation"
                )
            self.requirement_repository.apply_authorized_change(
                requirement,
                state=effect.proposed_state,
                expected_date=effect.proposed_expected_date,
            )
            applied_ids.append(requirement.id)

        applied_at = datetime.now(UTC)
        self.lineage_repository.mark_transition_applied(
            transition,
            applied_at=applied_at,
        )
        if self.lineage_repository.get_audit_event(
            event_type=REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT,
            policy_evaluation_id=evaluation.id,
            project_id=project_id,
        ) is None:
            self.lineage_repository.create_audit_event(
                event_type=REQUIREMENT_POLICY_AUTO_APPLIED_AUDIT_EVENT,
                actor_type="system",
                correspondence_event_id=proposal.correspondence_event_id,
                project_id=project_id,
                ai_proposal_id=proposal.id,
                policy_evaluation_id=evaluation.id,
                state_transition_id=transition.id,
                details={
                    "policy_version": evaluation.policy_version,
                    "applied_requirement_ids": [
                        str(requirement_id) for requirement_id in applied_ids
                    ],
                    "applied_at": applied_at.isoformat(),
                },
            )
        return tuple(applied_ids)

    def _ensure_policy_audit(
        self,
        *,
        proposal: AIProposal,
        evaluation: PolicyEvaluation,
        result: RequirementPolicyResult,
        project_id: UUID | None,
    ) -> None:
        if self.lineage_repository.get_audit_event(
            event_type=REQUIREMENT_POLICY_EVALUATED_AUDIT_EVENT,
            policy_evaluation_id=evaluation.id,
            project_id=project_id,
        ) is not None:
            return
        self.lineage_repository.create_audit_event(
            event_type=REQUIREMENT_POLICY_EVALUATED_AUDIT_EVENT,
            actor_type="system",
            correspondence_event_id=proposal.correspondence_event_id,
            project_id=project_id,
            ai_proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            details={
                "policy_version": evaluation.policy_version,
                "decision": evaluation.decision.value,
                "triggered_rule_ids": [
                    rule.value for rule in result.triggered_rule_ids
                ],
            },
        )

    def _get_transition(
        self,
        evaluation: PolicyEvaluation | None,
        proposal_id: UUID,
    ) -> StateTransition | None:
        if evaluation is None:
            return None
        return self.lineage_repository.get_state_transition_for_update(
            policy_evaluation_id=evaluation.id,
            affected_entity_type=REQUIREMENT_RECONCILIATION_ENTITY_TYPE,
            affected_entity_id=proposal_id,
        )
