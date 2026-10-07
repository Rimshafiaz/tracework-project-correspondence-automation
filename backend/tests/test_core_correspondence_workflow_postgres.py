import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai import Agent, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ai.requirement_schemas import ExistingRequirementImpact, RequirementImpactDisposition, RequirementReconciliation, RequirementSourceEvidence
from app.ai.schemas import CandidateSignalReference, ProjectResolution, ResolutionEvidence, ResolutionStatus, ResolverSourceField, SourceTextEvidence
from app.models.ai_proposal import AIProposal
from app.models.audit_event import AuditEvent
from app.models.correspondence_project_link import CorrespondenceProjectLink
from app.models.enums import PolicyDecision, ProjectStatus, ProposalType, RequirementState
from app.models.policy_evaluation import PolicyEvaluation
from app.models.review_item import ReviewItem
from app.models.state_transition import StateTransition
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
from app.services.core_correspondence_workflow import CoreCorrespondenceWorkflowService, CoreWorkflowStatus
from app.services.evidence_lineage import EvidenceLineageService
from app.services.follow_up_lifecycle import FollowUpLifecycleService
from app.services.policy.project_identity_authorization import ProjectIdentityAuthorizationService
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationService
from app.services.policy.requirement_context import RequirementPolicyContextService
from app.services.project_activity import ProjectActivityService
from app.services.project_resolution import ProjectResolutionService
from app.services.project_resolution_context import ProjectResolutionContextService
from app.services.project_resolution_review_creation import ProjectResolutionReviewCreationService
from app.services.project_resolution_workflow import ProjectResolutionWorkflowService
from app.services.requirement_policy_workflow import RequirementPolicyWorkflowService
from app.services.requirement_reconciliation import RequirementReconciliationService
from app.services.requirement_reconciliation_context import RequirementReconciliationContextService
from app.services.requirement_review_creation import RequirementReviewCreationService

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def _agent(output, output_type):
    def respond(_messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, output.model_dump(mode="json"))]
        )

    return Agent(FunctionModel(respond), output_type=output_type)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured",
)
def test_postgres_core_path_persists_one_link_mutation_audit_activity_and_lineage():
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, expire_on_commit=False) as session:
                suffix = uuid4().hex[:10]
                correspondence = CorrespondenceEventRepository(session)
                attachments = AttachmentRepository(session)
                projects = ProjectRepository(session)
                identifiers = ProjectIdentifierRepository(session)
                contacts = ProjectContactRepository(session)
                links = CorrespondenceProjectLinkRepository(session)
                requirements = RequirementRepository(session)
                lineage = LineageRepository(session)
                reviews = ReviewItemRepository(session)
                follow_ups = FollowUpRepository(session)
                project = projects.create(
                    project_code=f"M17-{suffix}",
                    name=f"M17 Project {suffix}",
                    normalized_name=f"m17 project {suffix}",
                    status=ProjectStatus.ACTIVE,
                )
                contact = contacts.create(
                    project_id=project.id,
                    email_normalized=f"operator-{suffix}@example.test",
                    display_name="M17 Operator",
                )
                requirement = requirements.create(
                    project_id=project.id,
                    name="Provide verified report",
                )
                event = correspondence.create(
                    source="fixture",
                    external_event_id=f"m17-{suffix}",
                    sender_identifier=contact.email_normalized,
                    sender_email=contact.email_normalized,
                    subject="Project update",
                    body=(
                        f"For {project.project_code}, the report is available, "
                        "but final verification remains pending."
                    ),
                    received_at=datetime.now(UTC),
                )
                project_signal = CandidateSignalReference(
                    project_id=project.id,
                    signal_type="PROJECT_CODE",
                    matched_value=project.project_code.casefold(),
                    source="CORRESPONDENCE_EVENT",
                )
                contact_signal = CandidateSignalReference(
                    project_id=project.id,
                    signal_type="PROJECT_CONTACT",
                    matched_value=contact.email_normalized,
                    source="PROJECT_RECORD",
                    source_record_id=contact.id,
                )
                project_output = ProjectResolution(
                    status=ResolutionStatus.MATCHED,
                    project_ids=(project.id,),
                    evidence=(
                        ResolutionEvidence(
                            project_id=project.id,
                            signal_references=(project_signal, contact_signal),
                            source_evidence=(
                                SourceTextEvidence(
                                    correspondence_event_id=event.id,
                                    source_field=ResolverSourceField.BODY,
                                    excerpt=project.project_code,
                                ),
                            ),
                            interpretation="The correspondence identifies the project.",
                        ),
                    ),
                )
                excerpt = "final verification remains pending"
                requirement_output = RequirementReconciliation(
                    existing_impacts=(
                        ExistingRequirementImpact(
                            requirement_id=requirement.id,
                            disposition=RequirementImpactDisposition.UPDATE_PROPOSED,
                            proposed_state=RequirementState.PARTIAL,
                            evidence=(
                                RequirementSourceEvidence(
                                    correspondence_event_id=event.id,
                                    source_field=ResolverSourceField.BODY,
                                    excerpt=excerpt,
                                ),
                            ),
                            interpretation="The report is present but work remains.",
                        ),
                    )
                )
                project_authorization = ProjectIdentityAuthorizationService(
                    session=session,
                    lineage_repository=lineage,
                    project_identifier_repository=identifiers,
                    project_contact_repository=contacts,
                    project_link_repository=links,
                )
                project_workflow = ProjectResolutionWorkflowService(
                    authorization_service=project_authorization,
                    review_creation_service=ProjectResolutionReviewCreationService(
                        session=session,
                        lineage_repository=lineage,
                        review_repository=reviews,
                        project_link_repository=links,
                    ),
                )
                requirement_policy_context = RequirementPolicyContextService(
                    correspondence_repository=correspondence,
                    project_link_repository=links,
                    requirement_repository=requirements,
                    attachment_repository=attachments,
                    lineage_repository=lineage,
                )
                workflow = CoreCorrespondenceWorkflowService(
                    session=session,
                    correspondence_repository=correspondence,
                    project_link_repository=links,
                    lineage_repository=lineage,
                    project_context_service=ProjectResolutionContextService(
                        correspondence_repository=correspondence,
                        attachment_repository=attachments,
                        project_repository=projects,
                        identifier_repository=identifiers,
                        contact_repository=contacts,
                        project_link_repository=links,
                    ),
                    project_resolution_service=ProjectResolutionService(
                        agent=_agent(project_output, ProjectResolution),
                        lineage_repository=lineage,
                        model_identifier="function:m17-project",
                    ),
                    project_workflow_service=project_workflow,
                    requirement_context_service=RequirementReconciliationContextService(
                        project_link_repository=links,
                        correspondence_repository=correspondence,
                        requirement_repository=requirements,
                        attachment_repository=attachments,
                        lineage_repository=lineage,
                        max_requirements=20,
                        max_attachments=10,
                        max_source_characters=50_000,
                    ),
                    requirement_reconciliation_service=RequirementReconciliationService(
                        agent=_agent(requirement_output, RequirementReconciliation),
                        lineage_repository=lineage,
                        model_identifier="function:m17-requirement",
                    ),
                    requirement_workflow_service=RequirementPolicyWorkflowService(
                        authorization_service=RequirementPolicyAuthorizationService(
                            session=session,
                            context_service=requirement_policy_context,
                            lineage_repository=lineage,
                            requirement_repository=requirements,
                            follow_up_lifecycle_service=FollowUpLifecycleService(
                                session=session,
                                requirement_repository=requirements,
                                follow_up_repository=follow_ups,
                                audit_repository=lineage,
                            ),
                        ),
                        review_creation_service=RequirementReviewCreationService(
                            session=session,
                            lineage_repository=lineage,
                            requirement_repository=requirements,
                            review_repository=reviews,
                        ),
                    ),
                )

                first = asyncio.run(workflow.process(event.id))
                second = asyncio.run(workflow.process(event.id))

                assert first.status is CoreWorkflowStatus.COMPLETED
                assert second.status is CoreWorkflowStatus.ALREADY_COMPLETED
                assert requirements.get(requirement.id).state is RequirementState.PARTIAL
                assert first.project_decision is PolicyDecision.ALLOW_AUTO_ACTION
                assert first.requirement_outcomes[0].decision is PolicyDecision.ALLOW_AUTO_ACTION
                proposal_ids = tuple(
                    session.scalars(
                        select(AIProposal.id).where(
                            AIProposal.correspondence_event_id == event.id
                        )
                    )
                )
                assert len(proposal_ids) == 2
                assert session.scalar(
                    select(func.count())
                    .select_from(PolicyEvaluation)
                    .where(PolicyEvaluation.ai_proposal_id.in_(proposal_ids))
                ) == 2
                assert session.scalar(
                    select(func.count())
                    .select_from(StateTransition)
                    .where(StateTransition.ai_proposal_id.in_(proposal_ids))
                ) == 2
                assert session.scalar(
                    select(func.count())
                    .select_from(ReviewItem)
                    .where(ReviewItem.correspondence_event_id == event.id)
                ) == 0
                assert session.scalar(
                    select(func.count())
                    .select_from(CorrespondenceProjectLink)
                    .where(CorrespondenceProjectLink.correspondence_event_id == event.id)
                ) == 1
                transition_id = first.requirement_outcomes[0].state_transition_id
                assert transition_id is not None
                assert EvidenceLineageService(
                    lineage_repository=lineage,
                    correspondence_repository=correspondence,
                    attachment_repository=attachments,
                    project_link_repository=links,
                    requirement_repository=requirements,
                    review_repository=reviews,
                ).load(transition_id).transition.status.value == "APPLIED"
                activity = ProjectActivityService(
                    project_repository=projects,
                    lineage_repository=lineage,
                ).load(project.id)
                assert any(item.state_transition_id == transition_id for item in activity.events)
                assert session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.correspondence_event_id == event.id)
                ) >= 6
        finally:
            transaction.rollback()
            engine.dispose()
