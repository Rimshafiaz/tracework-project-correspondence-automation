from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.schemas import ProjectResolution, ResolutionStatus
from app.contracts.project_candidate import CandidateSignalType, ProjectCandidateSet, ProjectCandidateSnapshotError, reconstruct_project_candidate_snapshot
from app.contracts.project_identity_policy import ProjectIdentityPolicyContext, ProjectIdentityPolicyResult
from app.models.ai_proposal import AIProposal
from app.models.correspondence_project_link import CorrespondenceProjectLink
from app.contracts.project_resolution_review_queue import PROJECT_RESOLUTION_LINK_ENTITY_TYPE
from app.models.enums import EvidenceValidity, PolicyDecision, TransitionDisposition, TransitionStatus
from app.models.policy_evaluation import PolicyEvaluation
from app.models.state_transition import StateTransition
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.services.policy.project_identity import evaluate_project_identity, reject_missing_candidate_snapshot
from app.services.policy.project_identity_persistence import persist_project_identity_policy_result
from app.services.policy.project_identity_rules import PROJECT_IDENTITY_POLICY_VERSION
from app.services.project_resolution_review_preview import build_project_link_authorization_preview

POLICY_EVALUATED_AUDIT_EVENT = "project_identity_policy_evaluated"
AUTO_LINKED_AUDIT_EVENT = "correspondence_project_link_auto_created"


class ProjectIdentityAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectIdentityAuthorizationResult:
    evaluation: PolicyEvaluation
    project_links: tuple[CorrespondenceProjectLink, ...]
    policy_evaluation_created: bool
    created_project_link_ids: tuple[UUID, ...]
    transition: StateTransition | None = None


class ProjectIdentityAuthorizationService:
    def __init__(
        self,
        *,
        session: Session,
        lineage_repository: LineageRepository,
        project_identifier_repository: ProjectIdentifierRepository,
        project_contact_repository: ProjectContactRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
    ) -> None:
        self.session = session
        self.lineage_repository = lineage_repository
        self.project_identifier_repository = project_identifier_repository
        self.project_contact_repository = project_contact_repository
        self.project_link_repository = project_link_repository

    def authorize(self, proposal_id: UUID) -> ProjectIdentityAuthorizationResult:
        try:
            proposal = self.lineage_repository.get_proposal_for_update(proposal_id)
            if proposal is None:
                raise ProjectIdentityAuthorizationError(
                    "project-resolution proposal was not found"
                )
            resolution = self._parse_resolution(proposal)
            existing = self.lineage_repository.get_policy_evaluation(
                ai_proposal_id=proposal.id,
                policy_version=PROJECT_IDENTITY_POLICY_VERSION,
            )
            if existing is None:
                policy_result = self._evaluate_new(proposal, resolution)
                persisted = persist_project_identity_policy_result(
                    policy_result,
                    self.lineage_repository,
                )
                evaluation = persisted.evaluation
                evaluation_created = persisted.created
            else:
                evaluation = existing
                evaluation_created = False

            self._ensure_policy_audit(proposal, resolution, evaluation)
            links, created_link_ids, transition = self._ensure_authorized_links(
                proposal,
                resolution,
                evaluation,
            )
            self.session.commit()
            return ProjectIdentityAuthorizationResult(
                evaluation=evaluation,
                project_links=links,
                policy_evaluation_created=evaluation_created,
                created_project_link_ids=created_link_ids,
                transition=transition,
            )
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _parse_resolution(proposal: AIProposal) -> ProjectResolution:
        try:
            return ProjectResolution.model_validate(proposal.structured_output)
        except ValidationError as exc:
            raise ProjectIdentityAuthorizationError(
                "persisted project resolution is invalid"
            ) from exc

    def _evaluate_new(
        self,
        proposal: AIProposal,
        resolution: ProjectResolution,
    ) -> ProjectIdentityPolicyResult:
        try:
            candidate_set = reconstruct_project_candidate_snapshot(
                proposal.input_metadata
            )
        except ProjectCandidateSnapshotError:
            return reject_missing_candidate_snapshot(
                proposal_id=proposal.id,
                resolver_status=resolution.status,
            )

        evidence = self.lineage_repository.list_proposal_evidence(proposal.id)
        candidate_evidence = self.lineage_repository.list_evidence_by_ids(
            {
                signal.evidence_item_id
                for candidate in candidate_set.candidates
                for signal in candidate.signals
                if signal.evidence_item_id is not None
            }
        )
        invalidated_evidence_ids = tuple(
            dict.fromkeys(
                item.id
                for item in (*evidence, *candidate_evidence)
                if item.validity is EvidenceValidity.INVALIDATED
            )
        )
        context = ProjectIdentityPolicyContext(
            proposal_id=proposal.id,
            correspondence_event_id=proposal.correspondence_event_id,
            proposal_type=proposal.proposal_type,
            resolution=resolution,
            candidate_set=candidate_set,
            proposal_evidence_ids=tuple(item.id for item in evidence),
            invalidated_evidence_ids=invalidated_evidence_ids,
            validated_source_record_ids=self._validated_source_record_ids(
                candidate_set
            ),
        )
        return evaluate_project_identity(context)

    def _validated_source_record_ids(
        self,
        candidate_set: ProjectCandidateSet,
    ) -> tuple[UUID, ...]:
        validated = []
        for candidate in candidate_set.candidates:
            for signal in candidate.signals:
                source_record_id = signal.source_record_id
                if source_record_id is None:
                    continue
                if signal.signal_type in {
                    CandidateSignalType.VERIFIED_IDENTIFIER,
                    CandidateSignalType.DOCUMENT_IDENTIFIER,
                    CandidateSignalType.ALIAS,
                    CandidateSignalType.FUZZY_ALIAS,
                }:
                    identifier = self.project_identifier_repository.get(
                        source_record_id
                    )
                    if (
                        identifier is not None
                        and identifier.project_id == candidate.project_id
                        and identifier.identifier_type == signal.identifier_type
                        and identifier.normalized_value == signal.matched_value
                        and identifier.verified
                    ):
                        validated.append(source_record_id)
                elif signal.signal_type is CandidateSignalType.PROJECT_CONTACT:
                    contact = self.project_contact_repository.get(source_record_id)
                    if (
                        contact is not None
                        and contact.project_id == candidate.project_id
                        and contact.email_normalized == signal.matched_value
                        and contact.is_active
                    ):
                        validated.append(source_record_id)
                elif signal.signal_type is CandidateSignalType.APPROVED_CONVERSATION:
                    link = self.project_link_repository.get(source_record_id)
                    if (
                        link is not None
                        and link.project_id == candidate.project_id
                        and signal.previously_approved
                    ):
                        validated.append(source_record_id)
        return tuple(dict.fromkeys(validated))

    def _ensure_policy_audit(
        self,
        proposal: AIProposal,
        resolution: ProjectResolution,
        evaluation: PolicyEvaluation,
    ) -> None:
        if self.lineage_repository.get_audit_event(
            event_type=POLICY_EVALUATED_AUDIT_EVENT,
            policy_evaluation_id=evaluation.id,
        ) is not None:
            return
        self.lineage_repository.create_audit_event(
            event_type=POLICY_EVALUATED_AUDIT_EVENT,
            actor_type="system",
            correspondence_event_id=proposal.correspondence_event_id,
            ai_proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            details={
                "resolver_status": resolution.status.value,
                "policy_version": evaluation.policy_version,
                "decision": evaluation.decision.value,
                "triggered_rule_ids": evaluation.triggered_rule_ids,
            },
        )

    def _ensure_authorized_links(
        self,
        proposal: AIProposal,
        resolution: ProjectResolution,
        evaluation: PolicyEvaluation,
    ) -> tuple[
        tuple[CorrespondenceProjectLink, ...],
        tuple[UUID, ...],
        StateTransition | None,
    ]:
        if evaluation.decision is not PolicyDecision.ALLOW_AUTO_ACTION:
            return (), (), None
        if resolution.status not in {
            ResolutionStatus.MATCHED,
            ResolutionStatus.MULTI_PROJECT,
        }:
            raise ProjectIdentityAuthorizationError(
                "an automatic policy decision requires a matched project resolution"
            )

        existing_transition = self.lineage_repository.get_state_transition_for_update(
            policy_evaluation_id=evaluation.id,
            affected_entity_type=PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
            affected_entity_id=proposal.correspondence_event_id,
        )
        if existing_transition is not None:
            if (
                existing_transition.disposition is not TransitionDisposition.AUTO_APPLY
                or existing_transition.status is not TransitionStatus.APPLIED
            ):
                raise ProjectIdentityAuthorizationError(
                    "automatic project-link transition is not applied"
                )
            return (
                self._load_authorized_links(proposal, resolution),
                (),
                existing_transition,
            )

        current_project_ids = tuple(
            self.project_link_repository.list_approved_project_ids_for_event(
                proposal.correspondence_event_id
            )
        )
        policy_evidence = self.lineage_repository.list_policy_evidence(
            evaluation.id
        )
        preview = build_project_link_authorization_preview(
            correspondence_event_id=proposal.correspondence_event_id,
            current_project_ids=current_project_ids,
            authorized_project_ids=resolution.project_ids,
            evidence_ids=tuple(item.id for item in policy_evidence),
            evaluation=evaluation,
        )
        if preview is None:
            return self._load_authorized_links(proposal, resolution), (), None

        transition = self.lineage_repository.create_transition(
            ai_proposal_id=proposal.id,
            policy_evaluation_id=evaluation.id,
            affected_entity_type=PROJECT_RESOLUTION_LINK_ENTITY_TYPE,
            affected_entity_id=proposal.correspondence_event_id,
            current_state={
                "project_ids": [
                    str(project_id) for project_id in preview.current_project_ids
                ]
            },
            proposed_state={
                "authorized_project_ids": [
                    str(project_id) for project_id in preview.authorized_project_ids
                ],
                "added_project_ids": [
                    str(project_id) for project_id in preview.added_project_ids
                ],
                "project_ids": [
                    str(project_id) for project_id in preview.result_project_ids
                ],
            },
            requirement_effects=[],
            document_effects=[],
            follow_up_effects=[],
            disposition=preview.disposition,
            evidence_item_ids=preview.evidence_ids,
        )

        links_by_project = {}
        created_link_ids = []
        for project_id in preview.added_project_ids:
            link, created = self.project_link_repository.get_or_create_approved_link(
                correspondence_event_id=proposal.correspondence_event_id,
                project_id=project_id,
            )
            if not created:
                raise ProjectIdentityAuthorizationError(
                    "project link changed while authorization was being applied"
                )
            links_by_project[project_id] = link
            created_link_ids.append(link.id)

        applied_at = datetime.now(UTC)
        self.lineage_repository.mark_transition_applied(
            transition,
            applied_at=applied_at,
        )
        for project_id in preview.added_project_ids:
            link = links_by_project[project_id]
            self.lineage_repository.create_audit_event(
                event_type=AUTO_LINKED_AUDIT_EVENT,
                actor_type="system",
                correspondence_event_id=proposal.correspondence_event_id,
                project_id=project_id,
                ai_proposal_id=proposal.id,
                policy_evaluation_id=evaluation.id,
                state_transition_id=transition.id,
                details={
                    "authorization": "AUTO_POLICY",
                    "correspondence_project_link_id": str(link.id),
                    "policy_version": evaluation.policy_version,
                    "created": True,
                    "applied_at": applied_at.isoformat(),
                },
            )
        return (
            self._load_authorized_links(proposal, resolution),
            tuple(created_link_ids),
            transition,
        )

    def _load_authorized_links(
        self,
        proposal: AIProposal,
        resolution: ProjectResolution,
    ) -> tuple[CorrespondenceProjectLink, ...]:
        links = []
        for project_id in resolution.project_ids:
            link = self.project_link_repository.get_approved_link(
                correspondence_event_id=proposal.correspondence_event_id,
                project_id=project_id,
            )
            if link is None:
                raise ProjectIdentityAuthorizationError(
                    "authorized project link is missing"
                )
            links.append(link)
        return tuple(links)
