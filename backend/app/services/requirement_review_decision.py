from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.requirement_schemas import RequirementCorrectionKind, RequirementReconciliation
from app.contracts.requirement_review_decision import RequirementReviewAction
from app.models.enums import PolicyDecision, RequirementState, ReviewStatus, ReviewType, TransitionDisposition, TransitionStatus
from app.repositories.lineage import LineageRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository, ReviewItemStateError
from app.services.follow_up_lifecycle import FollowUpLifecycleService
from app.services.policy.requirement import evaluate_requirement_policy
from app.services.policy.requirement_context import RequirementPolicyContextError, RequirementPolicyContextService
from app.services.policy.requirement_persistence import REQUIREMENT_RECONCILIATION_ENTITY_TYPE
from app.services.policy.requirement_rules import REQUIREMENT_POLICY_VERSION


REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT = "requirement_review_approved"
REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT = "requirement_review_rejected"


class RequirementReviewDecisionCode(StrEnum):
    REMAINING_SUPPORTING_EVIDENCE = "REMAINING_SUPPORTING_EVIDENCE"


class RequirementReviewDecisionError(RuntimeError):
    def __init__(self, message: str, *, code: RequirementReviewDecisionCode | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RequirementReviewDecisionResult:
    review_item: object
    action: RequirementReviewAction
    applied_requirement_ids: tuple[UUID, ...]
    follow_up_ids: tuple[UUID, ...]
    idempotent_replay: bool


class RequirementReviewDecisionService:
    """Applies one already-reviewed M11/M12 requirement proposal under fresh locks."""

    def __init__(
        self,
        *,
        session: Session,
        review_repository: ReviewItemRepository,
        lineage_repository: LineageRepository,
        requirement_repository: RequirementRepository,
        context_service: RequirementPolicyContextService,
        follow_up_lifecycle_service: FollowUpLifecycleService,
    ) -> None:
        if follow_up_lifecycle_service.session is not session:
            raise ValueError("requirement review services must share one session")
        self.session = session
        self.reviews = review_repository
        self.lineage = lineage_repository
        self.requirements = requirement_repository
        self.context = context_service
        self.follow_ups = follow_up_lifecycle_service

    def approve(
        self,
        review_item_id: UUID,
        *,
        operator_subject: str,
    ) -> RequirementReviewDecisionResult:
        return self._resolve(
            review_item_id,
            action=RequirementReviewAction.APPROVE,
            operator_subject=operator_subject,
        )

    def reject(
        self,
        review_item_id: UUID,
        *,
        operator_subject: str,
    ) -> RequirementReviewDecisionResult:
        return self._resolve(
            review_item_id,
            action=RequirementReviewAction.REJECT,
            operator_subject=operator_subject,
        )

    def _resolve(
        self,
        review_item_id: UUID,
        *,
        action: RequirementReviewAction,
        operator_subject: str,
    ) -> RequirementReviewDecisionResult:
        if not operator_subject.strip():
            raise ValueError("operator_subject must not be blank")
        try:
            review = self.reviews.get_for_update(review_item_id)
            if review is None:
                raise RequirementReviewDecisionError("requirement review item was not found")
            if review.review_type not in {
                ReviewType.REQUIREMENT_CHANGE,
                ReviewType.NEW_REQUIREMENT,
                ReviewType.RETRACTION_CORRECTION,
            }:
                raise RequirementReviewDecisionError("review item is not a requirement review")
            transition = self.lineage.get_state_transition_by_id_for_update(review.state_transition_id)
            if transition is None:
                raise RequirementReviewDecisionError("requirement review transition was not found")
            evaluation = self.lineage.get_policy_evaluation_by_id_for_update(
                transition.policy_evaluation_id
            )
            proposal = self.lineage.get_proposal_for_update(transition.ai_proposal_id)
            self._validate_lineage(review, transition, evaluation, proposal)
            if review.review_type is ReviewType.RETRACTION_CORRECTION:
                reconciliation = RequirementReconciliation.model_validate(proposal.structured_output)
                if not reconciliation.corrections:
                    raise RequirementReviewDecisionError("requirement review type does not match its proposal")

            if review.status is not ReviewStatus.PENDING:
                result = self._idempotent_result(review, action)
                self.session.commit()
                return result

            now = datetime.now(UTC)
            if action is RequirementReviewAction.REJECT:
                self.lineage.mark_transition_rejected(transition)
                self.reviews.mark_rejected(review, resolved_at=now)
                self._audit(
                    event_type=REQUIREMENT_REVIEW_REJECTED_AUDIT_EVENT,
                    review=review,
                    transition=transition,
                    evaluation=evaluation,
                    proposal=proposal,
                    operator_subject=operator_subject,
                    applied_requirement_ids=(),
                    project_id=context_project_id(transition.current_state),
                )
                self.session.commit()
                return RequirementReviewDecisionResult(
                    review_item=review,
                    action=action,
                    applied_requirement_ids=(),
                    follow_up_ids=(),
                    idempotent_replay=False,
                )

            context = self.context.build(proposal, lock_current_requirements=True)
            if bool(context.reconciliation.corrections) != (review.review_type is ReviewType.RETRACTION_CORRECTION):
                raise RequirementReviewDecisionError("requirement review type does not match its proposal")
            result = evaluate_requirement_policy(context)
            self._require_current_review_result(result, evaluation, transition)
            correction_requirements = self._apply_corrections(
                context, proposal, transition, now
            ) if review.review_type is ReviewType.RETRACTION_CORRECTION else ()
            applied_requirements = (*correction_requirements, *self._apply_effects(
                context, result, allow_empty=bool(correction_requirements)
            ))
            self.lineage.mark_transition_applied(transition, applied_at=now)
            lifecycle_results = tuple(
                self.follow_ups.reconcile(
                    requirement.id,
                    originating_state_transition_id=transition.id,
                    correspondence_event_id=proposal.correspondence_event_id,
                    ai_proposal_id=proposal.id,
                    policy_evaluation_id=evaluation.id,
                    actor_type="authenticated_operator",
                    actor_identifier=operator_subject,
                )
                for requirement in applied_requirements
            )
            self.reviews.mark_approved(review, resolved_at=now)
            applied_ids = tuple(requirement.id for requirement in applied_requirements)
            follow_up_ids = tuple(
                lifecycle.follow_up.id
                for lifecycle in lifecycle_results
                if lifecycle.follow_up is not None
            )
            self._audit(
                event_type=REQUIREMENT_REVIEW_APPROVED_AUDIT_EVENT,
                review=review,
                transition=transition,
                evaluation=evaluation,
                proposal=proposal,
                operator_subject=operator_subject,
                applied_requirement_ids=applied_ids,
                project_id=context.m11_snapshot.project_id,
            )
            self.session.commit()
            return RequirementReviewDecisionResult(
                review_item=review,
                action=action,
                applied_requirement_ids=applied_ids,
                follow_up_ids=follow_up_ids,
                idempotent_replay=False,
            )
        except (RequirementPolicyContextError, ReviewItemStateError) as exc:
            self.session.rollback()
            raise RequirementReviewDecisionError(str(exc)) from exc
        except Exception:
            self.session.rollback()
            raise

    def _validate_lineage(self, review, transition, evaluation, proposal) -> None:
        if (
            evaluation is None
            or proposal is None
            or evaluation.id != transition.policy_evaluation_id
            or proposal.id != transition.ai_proposal_id
            or proposal.correspondence_event_id != review.correspondence_event_id
            or evaluation.ai_proposal_id != proposal.id
            or evaluation.decision is not PolicyDecision.REVIEW_REQUIRED
            or evaluation.policy_version != REQUIREMENT_POLICY_VERSION
            or transition.affected_entity_type != REQUIREMENT_RECONCILIATION_ENTITY_TYPE
            or transition.affected_entity_id != proposal.id
            or transition.disposition is not TransitionDisposition.REVIEW
        ):
            raise RequirementReviewDecisionError("requirement review lineage is inconsistent")
        if review.status is ReviewStatus.PENDING and transition.status is not TransitionStatus.PREVIEWED:
            raise RequirementReviewDecisionError("requirement review transition is no longer applicable")

    def _require_current_review_result(self, result, evaluation, transition) -> None:
        if result.decision is not PolicyDecision.REVIEW_REQUIRED:
            raise RequirementReviewDecisionError("requirement proposal is no longer review-applicable")
        if (
            tuple(effect.model_dump(mode="json") for effect in result.requirement_effects)
            != tuple(transition.requirement_effects)
        ):
            raise RequirementReviewDecisionError("requirement proposal changed after review")
        persisted_evidence_ids = {
            item.id for item in self.lineage.list_policy_evidence(evaluation.id)
        }
        if set(result.evidence_ids) != persisted_evidence_ids:
            raise RequirementReviewDecisionError("requirement evidence changed after review")

    def _apply_corrections(self, context, proposal, transition, now):
        corrections = context.reconciliation.corrections
        if transition.proposed_state.get("correction_candidates") != [
            item.model_dump(mode="json") for item in corrections
        ]:
            raise RequirementReviewDecisionError("correction proposal changed after review")
        prepared = []
        project_id = context.m11_snapshot.project_id
        for correction in corrections:
            requirement = self.requirements.get_for_update(correction.requirement_id)
            if (
                requirement is None or requirement.project_id != project_id
                or requirement.state is not correction.previous_state
                or requirement.expected_date != correction.previous_expected_date
                or requirement.state is RequirementState.RETRACTED
            ):
                raise RequirementReviewDecisionError("requirement changed after correction review")
            valid_evidence = self.lineage.list_valid_requirement_evidence_for_update(
                project_id=project_id, requirement_id=requirement.id
            )
            valid_by_id = {item.id: item for item in valid_evidence}
            targeted = set(correction.target_evidence_item_ids)
            if not targeted.issubset(valid_by_id):
                raise RequirementReviewDecisionError("targeted evidence changed after review")
            source_ids = {
                item.evidence_item_id for item in context.proposal_evidence
                if item.requirement_id == requirement.id
                and any(
                    item.correspondence_event_id == source.correspondence_event_id
                    and item.attachment_id == source.attachment_id
                    and item.source_type == source.source_field.value.lower()
                    and item.excerpt == source.excerpt
                    for source in correction.evidence
                )
            }
            if not source_ids or not source_ids.issubset(valid_by_id):
                raise RequirementReviewDecisionError("correcting source evidence changed after review")
            if correction.kind is RequirementCorrectionKind.RETRACTION:
                remaining = set(valid_by_id) - targeted - source_ids
                if remaining:
                    raise RequirementReviewDecisionError(
                        "remaining supporting evidence requires reconciliation",
                        code=RequirementReviewDecisionCode.REMAINING_SUPPORTING_EVIDENCE,
                    )
            prepared.append((correction, requirement, tuple(valid_by_id[item] for item in targeted)))

        applied = []
        for correction, requirement, targeted in prepared:
            for evidence in targeted:
                self.lineage.invalidate_evidence(
                    evidence, correspondence_event_id=proposal.correspondence_event_id,
                    reason=f"Approved {correction.kind.value.lower()} review {transition.id}",
                    invalidated_at=now,
                )
            self.requirements.apply_authorized_change(
                requirement,
                state=(
                    RequirementState.RETRACTED
                    if correction.kind is RequirementCorrectionKind.RETRACTION
                    else correction.proposed_state or requirement.state
                ),
                expected_date=(
                    correction.proposed_expected_date
                    if correction.proposed_expected_date is not None
                    else requirement.expected_date
                ),
            )
            applied.append(requirement)
        return tuple(applied)

    def _apply_effects(self, context, result, *, allow_empty: bool = False):
        applied = []
        for effect in result.requirement_effects:
            requirement = self.requirements.get_for_update(effect.requirement_id)
            if (
                requirement is None
                or requirement.project_id != context.m11_snapshot.project_id
                or requirement.state is not effect.current_state
                or requirement.expected_date != effect.current_expected_date
            ):
                raise RequirementReviewDecisionError("requirement changed after review")
            self.requirements.apply_authorized_change(
                requirement,
                state=effect.proposed_state,
                expected_date=effect.proposed_expected_date,
            )
            applied.append(requirement)
        for index, proposed in enumerate(context.reconciliation.new_requirements):
            policy_result = result.new_requirement_results[index]
            if policy_result.decision is not PolicyDecision.REVIEW_REQUIRED:
                raise RequirementReviewDecisionError("new requirement is not review-applicable")
            applied.append(
                self.requirements.create(
                    project_id=context.m11_snapshot.project_id,
                    name=proposed.name,
                    description=proposed.description,
                    expected_date=proposed.expected_date,
                )
            )
        if not applied and not allow_empty:
            raise RequirementReviewDecisionError("requirement review has no applicable effects")
        return tuple(applied)

    def _audit(
        self,
        *,
        event_type: str,
        review,
        transition,
        evaluation,
        proposal,
        operator_subject: str,
        applied_requirement_ids: tuple[UUID, ...],
        project_id: UUID,
    ) -> None:
        self.lineage.create_audit_event(
            event_type=event_type,
            actor_type="authenticated_operator",
            actor_identifier=operator_subject,
            correspondence_event_id=proposal.correspondence_event_id,
            project_id=project_id,
            ai_proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            state_transition_id=transition.id,
            review_item_id=review.id,
            details={
                "authorization": "HUMAN_REVIEW",
                "action": event_type,
                "applied_requirement_ids": [str(item) for item in applied_requirement_ids],
            },
        )

    @staticmethod
    def _idempotent_result(review, action: RequirementReviewAction) -> RequirementReviewDecisionResult:
        expected = (
            ReviewStatus.APPROVED
            if action is RequirementReviewAction.APPROVE
            else ReviewStatus.REJECTED
        )
        if review.status is not expected:
            raise RequirementReviewDecisionError("review item has already been resolved differently")
        return RequirementReviewDecisionResult(
            review_item=review,
            action=action,
            applied_requirement_ids=(),
            follow_up_ids=(),
            idempotent_replay=True,
        )


def context_project_id(current_state: dict[str, object]) -> UUID:
    value = current_state.get("project_id")
    if not isinstance(value, str):
        raise RequirementReviewDecisionError("requirement review transition is missing project lineage")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RequirementReviewDecisionError("requirement review transition is missing project lineage") from exc
