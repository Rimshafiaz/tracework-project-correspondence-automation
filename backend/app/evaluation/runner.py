"""Single-case execution; production services run in a rollback-only schema."""

from contextlib import contextmanager
from hashlib import sha256

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from app.ai.resolver import build_project_resolver_agent
from app.ai.requirement_reconciler import build_requirement_reconciler_agent
from app.contracts.project_resolution_review_queue import ProjectResolutionReviewApproval
from app.core.config import Settings
from app.db.base import Base
from app.evaluation.actions import ActionType
from app.evaluation.contracts import (
    ActionExpectation, EvaluatedSystem, EvaluationCase, EvaluationCaseResult,
    EvaluationCorrection, EvaluationModelMetadata, EvaluationStage, EvaluationSystemResult,
    ExpectedConflict, ExpectedNewRequirement, ExpectedRequirementState,
)
from app.evaluation.project_resolver import _fixture_uuid
from app.models import (
    Attachment, CorrespondenceEvent, CorrespondenceProjectLink, EvidenceItem, FollowUp,
    Project, ProjectContact, ProjectIdentifier, Requirement, ReviewItem,
)
from app.models.enums import AttachmentProcessingState, EvidenceValidity, PolicyDecision, ReviewStatus, ReviewType
from app.normalization.correspondence import normalize_email, normalize_source
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.project_identifier import ProjectIdentifierRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.follow_up_lifecycle import FollowUpLifecycleService
from app.services.policy.project_identity_authorization import ProjectIdentityAuthorizationService
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationService
from app.services.policy.requirement_context import RequirementPolicyContextService
from app.services.project_resolution import ProjectResolutionService
from app.services.project_resolution_context import ProjectResolutionContextService
from app.services.project_resolution_review_creation import ProjectResolutionReviewCreationService
from app.services.project_resolution_review_decision import ProjectResolutionReviewDecisionError, ProjectResolutionReviewDecisionService
from app.services.requirement_reconciliation import RequirementReconciliationService
from app.services.requirement_reconciliation_context import RequirementReconciliationContextService
from app.services.requirement_review_creation import RequirementReviewCreationService
from app.services.requirement_review_decision import RequirementReviewDecisionError, RequirementReviewDecisionService


@contextmanager
def _case_session(engine: Engine, case_id: str):
    # Service commits release savepoints only; even the schema is rolled back.
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = f"tracework_eval_{_fixture_uuid('case', case_id).hex}"
            connection.execute(CreateSchema(schema))
            connection = connection.execution_options(schema_translate_map={None: schema})
            Base.metadata.create_all(connection)
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                yield session
        finally:
            transaction.rollback()


def _seed_case(session, case):
    labels = {}
    def identifier(kind, label):
        value = _fixture_uuid(kind, label)
        labels[value] = label
        return value

    for item in case.input.candidate_projects:
        project_id = identifier("project", item.project_id)
        session.add(Project(id=project_id, project_code=item.project_code, name=item.name, normalized_name=item.normalized_name))
    source = case.input.correspondence
    event = CorrespondenceEvent(id=_fixture_uuid("correspondence", source.external_event_id),
        **source.model_dump(exclude={"attachments", "source", "sender_email"}),
        source=normalize_source(source.source),
        sender_email=normalize_email(source.sender_email or source.sender_identifier) if "@" in (source.sender_email or source.sender_identifier) else None)
    session.add(event)
    session.flush()
    for project in case.input.candidate_projects:
        project_id = _fixture_uuid("project", project.project_id)
        for index, item in enumerate(project.identifiers):
            session.add(ProjectIdentifier(id=_fixture_uuid("identifier", f"{project.project_id}:{index}"), project_id=project_id, **item.model_dump()))
        for index, contact in enumerate(project.known_contact_identifiers):
            session.add(ProjectContact(id=_fixture_uuid("contact", f"{project.project_id}:{index}"), project_id=project_id, email_normalized=normalize_email(contact), display_name=contact))
    for item in case.input.requirements:
        session.add(Requirement(id=identifier("requirement", item.requirement_id),
            project_id=_fixture_uuid("project", item.project_id), **item.model_dump(exclude={"requirement_id", "project_id"})))
    for item in source.attachments:
        session.add(Attachment(id=identifier("attachment", item.attachment_id), correspondence_event_id=event.id,
            source_attachment_id=item.attachment_id, filename=item.filename, mime_type=item.mime_type,
            size_bytes=len((item.extracted_text or "").encode()), extracted_text=item.extracted_text,
            content_hash=sha256((item.extracted_text or "").encode()).hexdigest(),
            processing_state=AttachmentProcessingState.EXTRACTED if item.extracted_text is not None else AttachmentProcessingState.UNSUPPORTED))
    session.flush()
    for item in case.input.evidence:
        session.add(EvidenceItem(id=identifier("evidence", item.evidence_id), correspondence_event_id=event.id,
            project_id=_fixture_uuid("project", item.project_id) if item.project_id else None,
            requirement_id=_fixture_uuid("requirement", item.requirement_id) if item.requirement_id else None,
            attachment_id=_fixture_uuid("attachment", item.attachment_id) if item.attachment_id else None,
            source_type=item.source_type, excerpt=item.excerpt, page_number=item.page_number, section=item.section,
            validity=item.validity, invalidated_by_correspondence_event_id=event.id if item.validity is EvidenceValidity.INVALIDATED else None,
            invalidation_reason="Invalidated input fixture" if item.validity is EvidenceValidity.INVALIDATED else None,
            invalidated_at=source.received_at if item.validity is EvidenceValidity.INVALIDATED else None))
    session.flush()
    return event, labels


async def run_evaluation_case(case: EvaluationCase, *, engine: Engine, settings: Settings,
                              project_agent=None, requirement_agent=None) -> EvaluationCaseResult:
    """Use an explicitly supplied PostgreSQL engine; never select a live DB implicitly."""
    diagnostics, models = [], []
    phase = "setup"
    try:
        stages = case.stages
        if engine.dialect.name != "postgresql":
            return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Evaluation requires PostgreSQL schema isolation")
        if stages[0] is not EvaluationStage.PROJECT_RESOLUTION or tuple(sorted(stages, key=list(EvaluationStage).index)) != stages:
            return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Stages must start with project resolution and follow pipeline order")
        if EvaluationStage.REQUIREMENT_RECONCILIATION in stages and EvaluationStage.POLICY not in stages:
            return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Reconciliation requires the policy stage to authorize project scope")
        if EvaluationStage.REVIEW_APPLICATION in stages and EvaluationStage.POLICY not in stages:
            return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Review application requires the policy stage")

        with _case_session(engine, case.case_id) as session:
            event, labels = _seed_case(session, case)
            lineage, requirements = LineageRepository(session), RequirementRepository(session)
            correspondence, attachments = CorrespondenceEventRepository(session), AttachmentRepository(session)
            links, reviews = CorrespondenceProjectLinkRepository(session), ReviewItemRepository(session)
            projects, identifiers, contacts = ProjectRepository(session), ProjectIdentifierRepository(session), ProjectContactRepository(session)
            lifecycle = FollowUpLifecycleService(session=session, requirement_repository=requirements,
                follow_up_repository=FollowUpRepository(session), audit_repository=lineage)
            policy_context = RequirementPolicyContextService(correspondence_repository=correspondence,
                project_link_repository=links, requirement_repository=requirements, attachment_repository=attachments, lineage_repository=lineage)
            phase = "PROJECT_RESOLUTION"
            context = ProjectResolutionContextService(correspondence_repository=correspondence, attachment_repository=attachments,
                project_repository=projects, identifier_repository=identifiers, contact_repository=contacts, project_link_repository=links).build(event.id)
            resolved = await ProjectResolutionService(agent=project_agent or build_project_resolver_agent(settings),
                lineage_repository=lineage, model_identifier=settings.project_resolver_model).resolve(context)
            diagnostics.append(phase)
            proposal, evaluation, reconciliation = resolved.proposal, None, None
            if resolved.agent_invoked:
                models.append(EvaluationModelMetadata(stage=EvaluationStage.PROJECT_RESOLUTION, provider=settings.project_resolver_provider,
                    model=proposal.model_identifier, prompt_version=proposal.prompt_version))
            authorized_links = ()
            if EvaluationStage.POLICY in stages:
                phase = "POLICY:PROJECT"
                authorized = ProjectIdentityAuthorizationService(session=session, lineage_repository=lineage,
                    project_identifier_repository=identifiers, project_contact_repository=contacts, project_link_repository=links).authorize(proposal.id)
                evaluation, authorized_links = authorized.evaluation, authorized.project_links
                diagnostics.append(phase)
                if evaluation.decision is PolicyDecision.REVIEW_REQUIRED:
                    ProjectResolutionReviewCreationService(session=session, lineage_repository=lineage,
                        review_repository=reviews, project_link_repository=links).ensure_review_for_policy_evaluation(evaluation.id)

            if EvaluationStage.REQUIREMENT_RECONCILIATION in stages:
                if len(authorized_links) > 1:
                    return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Single-case reconciliation currently requires one authorized project", diagnostics=tuple(diagnostics), models=tuple(models))
                if not authorized_links:
                    diagnostics.append("REQUIREMENT_RECONCILIATION skipped: project scope was not authorized")
                else:
                    phase = "REQUIREMENT_RECONCILIATION"
                    context = RequirementReconciliationContextService(project_link_repository=links, correspondence_repository=correspondence,
                        requirement_repository=requirements, attachment_repository=attachments, lineage_repository=lineage,
                        max_requirements=settings.requirement_reconciler_max_requirements,
                        max_attachments=settings.requirement_reconciler_max_attachments,
                        max_source_characters=settings.requirement_reconciler_max_source_characters).build(authorized_links[0].id)
                    reconciled = await RequirementReconciliationService(agent=requirement_agent or build_requirement_reconciler_agent(settings),
                        lineage_repository=lineage, model_identifier=settings.requirement_reconciler_model).reconcile(context)
                    reconciliation, proposal = reconciled.reconciliation, reconciled.proposal
                    diagnostics.append(phase)
                    models.append(EvaluationModelMetadata(stage=EvaluationStage.REQUIREMENT_RECONCILIATION, provider=settings.requirement_reconciler_provider,
                        model=proposal.model_identifier, prompt_version=proposal.prompt_version))
                    phase = "POLICY:REQUIREMENT"
                    authorized = RequirementPolicyAuthorizationService(session=session, context_service=policy_context,
                        lineage_repository=lineage, requirement_repository=requirements, follow_up_lifecycle_service=lifecycle).authorize(proposal.id)
                    evaluation = authorized.evaluation
                    diagnostics.append(phase)
                    if evaluation.decision is PolicyDecision.REVIEW_REQUIRED:
                        RequirementReviewCreationService(session=session, lineage_repository=lineage,
                            requirement_repository=requirements, review_repository=reviews).ensure_review_for_policy_evaluation(evaluation.id)

            application_status, block_code = None, None
            if EvaluationStage.REVIEW_APPLICATION in stages:
                phase = "REVIEW_APPLICATION"
                pending = list(session.scalars(select(ReviewItem).where(ReviewItem.status == ReviewStatus.PENDING)))
                if len(pending) != 1:
                    return EvaluationCaseResult(case_id=case.case_id, status="ERROR", error="Explicit review application requires exactly one pending review", diagnostics=tuple(diagnostics), models=tuple(models))
                review = pending[0]
                if review.review_type is ReviewType.PROJECT_RESOLUTION:
                    service = ProjectResolutionReviewDecisionService(session=session, review_repository=reviews,
                        lineage_repository=lineage, project_repository=projects, project_link_repository=links)
                    decision = ProjectResolutionReviewApproval(actor={"actor_type": "authenticated_operator", "actor_identifier": "evaluation-operator"})
                    arguments = {"decision": decision}
                else:
                    service = RequirementReviewDecisionService(session=session, review_repository=reviews, lineage_repository=lineage,
                        requirement_repository=requirements, context_service=policy_context, follow_up_lifecycle_service=lifecycle)
                    arguments = {"operator_subject": "evaluation-operator"}
                try:
                    if case.review_action.value == "APPROVE":
                        service.approve(review.id, **arguments)
                    else:
                        service.reject(review.id, **arguments)
                    application_status = review.status.value
                except (RequirementReviewDecisionError, ProjectResolutionReviewDecisionError) as exc:
                    session.rollback()
                    application_status = "BLOCKED"
                    code = getattr(exc, "code", None)
                    block_code = code.value if code is not None else None
                diagnostics.extend((phase, f"review_status={review.status.value}"))

            phase = "capture"
            actual = _capture(session, case, labels, resolved.resolution, resolved.proposal, proposal, evaluation, reconciliation)
            actual = actual.model_copy(update={"review_application_status": application_status, "application_block_code": block_code})
            result = EvaluationCaseResult(case_id=case.case_id, status="UNSCORED", actual=actual,
                models=tuple(models), diagnostics=tuple(diagnostics))
        return result
    except Exception as exc:
        code = getattr(exc, "code", None)
        return EvaluationCaseResult(case_id=case.case_id, status="ERROR", diagnostics=tuple(diagnostics), models=tuple(models),
            error=f"{phase}: {type(exc).__name__}" + (f" ({code.value})" if code is not None and hasattr(code, "value") else ""))


def _capture(session, case, labels, resolution, project_proposal, proposal, evaluation, reconciliation):
    label = lambda value: labels.get(value, str(value))
    states, actions = [], []
    previous = {_fixture_uuid("requirement", item.requirement_id): item for item in case.input.requirements}
    for item in session.scalars(select(Requirement).order_by(Requirement.name, Requirement.id)):
        before = previous.get(item.id)
        if before is None:
            labels[item.id] = f"new-requirement:{item.name}"
            actions.append(ActionExpectation(action_type=ActionType.CREATE_REQUIREMENT, target_type="requirement",
                target_id=label(item.id), parameters={"name": item.name}))
        elif (before.state, before.expected_date) != (item.state, item.expected_date):
            actions.append(ActionExpectation(action_type=ActionType.CHANGE_REQUIREMENT_STATE, target_type="requirement",
                target_id=label(item.id), parameters={"state": item.state.value, "expected_date": item.expected_date.isoformat() if item.expected_date else None}))
        states.append(ExpectedRequirementState(requirement_id=label(item.id), state=item.state, expected_date=item.expected_date))
    for item in session.scalars(select(CorrespondenceProjectLink).order_by(CorrespondenceProjectLink.project_id)):
        actions.append(ActionExpectation(action_type=ActionType.LINK_CORRESPONDENCE_TO_PROJECT, target_type="project", target_id=label(item.project_id)))
    for item in session.scalars(select(ReviewItem).order_by(ReviewItem.review_type)):
        actions.append(ActionExpectation(action_type=ActionType.CREATE_REVIEW, target_type="review", target_id=item.review_type.value))
    for item in session.scalars(select(FollowUp).order_by(FollowUp.requirement_id)):
        actions.append(ActionExpectation(action_type=ActionType.CREATE_FOLLOW_UP, target_type="requirement", target_id=label(item.requirement_id)))
    original_evidence = {_fixture_uuid("evidence", item.evidence_id): item for item in case.input.evidence}
    for item in session.scalars(select(EvidenceItem)):
        before = original_evidence.get(item.id)
        if before and before.validity is EvidenceValidity.VALID and item.validity is EvidenceValidity.INVALIDATED:
            actions.append(ActionExpectation(action_type=ActionType.INVALIDATE_EVIDENCE, target_type="evidence", target_id=label(item.id)))
    def proposal_evidence(proposal):
        items = sorted(LineageRepository(session).list_proposal_evidence(proposal.id),
            key=lambda item: (item.source_type, label(item.requirement_id), item.excerpt,
                label(item.attachment_id), *(str((item.provenance_metadata or {}).get(key, "")) for key in
                    ("candidate_project_id", "signal_source", "identifier_type", "source_record_id"))))
        for index, item in enumerate(items):
            if item.id not in labels:
                labels[item.id] = f"source-evidence:{proposal.proposal_type.value}:{index}"
        return items
    evidence = proposal_evidence(proposal)
    project_evidence = proposal_evidence(project_proposal)
    def reference_ids(references, requirement_id=None, items=None):
        items = evidence if items is None else items
        return tuple(dict.fromkeys(label(item.id) for reference in references for item in items
            if (getattr(reference, "evidence_item_id", None) == item.id) or (
                hasattr(reference, "source_field") and item.requirement_id == requirement_id
                and item.correspondence_event_id == reference.correspondence_event_id
                and item.attachment_id == reference.attachment_id
                and item.source_type == reference.source_field.value.lower()
                and item.excerpt == reference.excerpt) or (
                hasattr(reference, "signal_type") and item.excerpt == reference.matched_value
                and item.attachment_id == reference.attachment_id
                and item.source_type == f"candidate_signal:{reference.signal_type.value.lower()}"
                and (item.provenance_metadata or {}).get("candidate_project_id") == str(reference.project_id)
                and (item.provenance_metadata or {}).get("signal_source") == reference.source.value
                and (item.provenance_metadata or {}).get("identifier_type") == reference.identifier_type
                and (item.provenance_metadata or {}).get("source_record_id") == (
                    str(reference.source_record_id) if reference.source_record_id is not None else None))))
    new_requirements = tuple(ExpectedNewRequirement(name=item.name, evidence_ids=reference_ids(item.evidence))
        for item in reconciliation.new_requirements) if reconciliation else ()
    return EvaluationSystemResult(system=EvaluatedSystem.TRACEWORK, stages=case.stages,
        project_resolution=resolution.status.value, project_ids=tuple(label(value) for value in resolution.project_ids),
        requirement_states=tuple(states), review_required=evaluation.decision is PolicyDecision.REVIEW_REQUIRED if evaluation else resolution.status.value == "REVIEW_REQUIRED",
        policy={"policy_version": evaluation.policy_version, "decision": evaluation.decision, "triggered_rule_ids": evaluation.triggered_rule_ids, "reasons": evaluation.reasons} if evaluation else None,
        proposal_type=proposal.proposal_type, evidence_ids=tuple(label(item.id) for item in evidence), actions=tuple(actions), new_requirements=new_requirements,
        conflicts=tuple(ExpectedConflict(conflict_type="project_identity", evidence_ids=reference_ids(
            (*item.signal_references, *item.source_evidence), items=project_evidence), description=item.description)
            for item in resolution.conflicts) + (tuple(ExpectedConflict(conflict_type="requirement_evidence",
            evidence_ids=reference_ids(item.evidence, item.requirement_ids[0] if len(item.requirement_ids) == 1 else None),
            description=item.description) for item in reconciliation.conflicts) if reconciliation else ()),
        corrections=tuple(EvaluationCorrection(requirement_id=label(item.requirement_id), kind=item.kind,
            target_evidence_ids=tuple(label(value) for value in item.target_evidence_item_ids), proposed_state=item.proposed_state,
            proposed_expected_date=item.proposed_expected_date) for item in reconciliation.corrections) if reconciliation else ())
