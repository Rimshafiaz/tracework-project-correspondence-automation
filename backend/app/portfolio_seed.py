"""Offline synthetic portfolio data. Run from backend: python -m app.portfolio_seed.

Requires an empty, migrated TEST_DATABASE_URL distinct from DATABASE_URL,
APP_ENV=development|test, GMAIL_ENABLED=false and DRIVE_ENABLED=false.
Never run against a live-data target. No model or integration client is created.
"""

import asyncio
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.ai.reply_drafter import get_due_follow_up, get_project_summary, get_requirement_context
from app.ai.reply_drafter_schemas import ReplyDraftProposal
from app.ai.requirement_schemas import ExistingRequirementImpact, RequirementCorrectionProposal, RequirementReconciliation, RequirementSourceEvidence
from app.core.config import Settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models.enums import PolicyDecision, RequirementState
from app.normalization.project_identity import normalize_project_name
from app.repositories.attachment import AttachmentRepository
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import CorrespondenceProjectLinkRepository
from app.repositories.document import DocumentRepository
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project import ProjectRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.reply_draft import ReplyDraftRepository
from app.repositories.requirement import RequirementRepository
from app.repositories.review_item import ReviewItemRepository
from app.services.follow_up_due import FollowUpDueService
from app.services.follow_up_lifecycle import FollowUpLifecycleService
from app.services.follow_up_read import FollowUpReadService
from app.services.policy.requirement_authorization import RequirementPolicyAuthorizationService
from app.services.policy.requirement_context import RequirementPolicyContextService
from app.services.reply_draft_eligibility import ReplyDraftEligibilityService
from app.services.reply_draft_generation import ReplyDraftGenerationService, ReplyDraftGroundingValidator
from app.services.reply_drafter_runner import ReplyDrafterRunner
from app.services.requirement_reconciliation import RequirementReconciliationService
from app.services.requirement_reconciliation_context import RequirementReconciliationContextService
from app.services.requirement_review_creation import RequirementReviewCreationService
from app.services.requirement_review_decision import RequirementReviewDecisionService
from app.services.scoped_reply_draft_context import ScopedReplyDraftContextService


class _PreparedProposal:
    """Authored synthetic output, not an actual model response."""

    def __init__(self, proposal):
        self.proposal = proposal

    async def run(self, _prompt):
        return SimpleNamespace(output=self.proposal)


class _PreparedReply:
    async def run(self, _prompt, *, deps, usage_limits):
        ctx = SimpleNamespace(deps=deps)
        get_due_follow_up(ctx)
        get_project_summary(ctx)
        requirement = get_requirement_context(ctx)
        references = tuple(dict.fromkeys(
            reference for entry in deps.trace.snapshot().entries
            for reference in entry.exposed_references
        ))
        return SimpleNamespace(output=ReplyDraftProposal(
            reply_type="OVERDUE_FOLLOW_UP",
            subject="Brookfield Logistics Hub — commissioning certificates",
            body=("Hi Marcus,\n\n"
                  "I'm following up on the commissioning certificates for Brookfield Logistics Hub. "
                  f"The revised submission date was {requirement.expected_date.strftime('%d %B')}, "
                  "and we haven't received the final pack yet.\n\n"
                  "Could you please confirm where things stand and when we can expect the signed certificates? "
                  "If anything is holding up submission, let us know so we can coordinate with the consultant.\n\n"
                  "Best regards,\nElena Ward\nProject Coordinator"),
            grounding_references=references,
        ))


def validate_target(settings: Settings, target: str | None) -> str:
    if settings.app_env == "production" or settings.gmail_enabled or settings.drive_enabled:
        raise ValueError("Synthetic seeding requires development/test with Gmail and Drive disabled")
    if not target:
        raise ValueError("An explicit separate TEST_DATABASE_URL is required")
    live, test = make_url(settings.database_url), make_url(target)
    if test.get_backend_name() != "postgresql":
        raise ValueError("TEST_DATABASE_URL must target PostgreSQL")
    # Supabase's shared pooler routes by tenant-qualified username, not database name.
    def identity(url):
        if (url.host or "").endswith(".pooler.supabase.com"):
            if not url.username or not url.username.startswith("postgres."):
                raise ValueError("Cannot establish the Supabase pooler tenant safely")
            return ("supabase", url.username.split(".", 1)[1], url.database)
        return (url.host, url.port or 5432, url.database)
    if identity(live) == identity(test):
        raise ValueError("TEST_DATABASE_URL must not target DATABASE_URL")
    return target


async def seed_portfolio(session: Session) -> dict[str, object]:
    """Caller owns an outer transaction; service commits must be savepoints."""
    if session.join_transaction_mode != "create_savepoint" or not session.get_bind().in_transaction():
        raise ValueError("Seed requires a caller-owned transaction and create_savepoint session")
    for table in Base.metadata.sorted_tables:
        if session.scalar(select(table).limit(1)) is not None:
            raise ValueError("Seed target must be empty; existing data will not be changed")
    projects, contacts = ProjectRepository(session), ProjectContactRepository(session)
    requirements, events = RequirementRepository(session), CorrespondenceEventRepository(session)
    links, lineage = CorrespondenceProjectLinkRepository(session), LineageRepository(session)
    follow_ups, reviews = FollowUpRepository(session), ReviewItemRepository(session)
    attachments, documents = AttachmentRepository(session), DocumentRepository(session)
    lifecycle = FollowUpLifecycleService(session=session, requirement_repository=requirements,
        follow_up_repository=follow_ups, audit_repository=lineage)
    today = date.today()
    operator = "elena.ward@alderstone-projects.co.uk"
    stories = (
        ("AR-RF-26-014", "Alder Row Retail Refurbishment", "Priya Desai", "priya.desai@carrick-interiors.co.uk", "Site Manager", (
            ("Revised joinery shop drawings", "Coordinate the reception desk and retail display interfaces.", 5),
            ("Close mezzanine snag items", "Finish the lighting trims and remaining access-panel adjustments.", 9),
            ("Issue weekend access schedule", "Confirm delivery slots and security coverage for the next installation weekend.", 3),
        )),
        ("WM-HC-26-008", "Westmere Medical Centre", "Sofia Bennett", "sofia.bennett@lynden-building.co.uk", "Contracts Manager", (
            ("Submit ventilation balancing report", "Provide the signed air-balancing results for the treatment rooms.", 7),
            ("Consultant sign-off on reception finishes", "Arrange final consultant inspection of the reception finishes.", 12),
        )),
        ("BL-LH-26-021", "Brookfield Logistics Hub", "Marcus Hale", "marcus.hale@fenwick-mep.co.uk", "Commissioning Lead", (
            ("Signed commissioning certificates", "Submit the signed mechanical and electrical commissioning pack.", -5),
            ("Confirm loading-bay material delivery", "Confirm the dock levellers and safety barriers against the agreed delivery slots.", 4),
        )),
    )
    created_projects, created_requirements, prior_evidence = [], [], []

    def correspondence(project, contact, subject, body, days_ago):
        event = events.create(
            source="gmail", external_event_id=f"synthetic-{uuid4().hex}",
            external_conversation_id=f"synthetic-{project.project_code}",
            sender_identifier=contact.email_normalized, sender_email=contact.email_normalized,
            sender_name=contact.display_name, subject=subject, body=body,
            received_at=datetime.combine(today - timedelta(days=days_ago), time(9, 15), UTC),
            source_metadata={"synthetic": True, "recipient": operator},
        )
        link = links.create_approved_link(correspondence_event_id=event.id, project_id=project.id)
        lineage.create_audit_event(event_type="correspondence_project_linked", actor_type="authenticated_operator",
            actor_identifier=operator, project_id=project.id, correspondence_event_id=event.id,
            details={"synthetic": True, "project_code": project.project_code})
        return event, link

    for code, name, person, email, role, obligations in stories:
        project = projects.create(project_code=code, name=name, normalized_name=normalize_project_name(name))
        contact = contacts.create(project_id=project.id, email_normalized=email, display_name=person, role=role)
        lineage.create_audit_event(event_type="project_created", actor_type="authenticated_operator",
            actor_identifier=operator, project_id=project.id, details={"name": name, "project_code": code, "synthetic": True})
        project_requirements = []
        lines = [f"Hi Elena,\n\nFollowing our coordination meeting for {name}, the next commitments are:"]
        for title, description, offset in obligations:
            expected = today + timedelta(days=offset)
            requirement = requirements.create(project_id=project.id, name=title, description=description, expected_date=expected)
            project_requirements.append(requirement)
            lines.append(f"- {title}: {expected.strftime('%d %B %Y')}.")
            initialized = lineage.create_audit_event(event_type="requirement_initialized", actor_type="authenticated_operator",
                actor_identifier=operator, project_id=project.id, requirement_id=requirement.id,
                details={"requirement_id": str(requirement.id), "name": title, "state": "OPEN", "expected_date": expected.isoformat(), "synthetic": True})
            lifecycle.reconcile(requirement.id, originating_audit_event_id=initialized.id,
                actor_type="authenticated_operator", actor_identifier=operator)
        lines.append(f"\nPlease flag any coordination issues before the next site meeting.\n\nRegards,\n{person}")
        event, _ = correspondence(project, contact, f"{code} — coordination commitments", "\n".join(lines), 8)
        evidence = [lineage.create_evidence(correspondence_event_id=event.id, source_type="body",
            project_id=project.id, requirement_id=item.id,
            excerpt=f"- {item.name}: {item.expected_date.strftime('%d %B %Y')}.",
            provenance_metadata={"synthetic": True}) for item in project_requirements]
        created_projects.append((project, contact))
        created_requirements.append(project_requirements)
        prior_evidence.append(evidence)

    policy_context = RequirementPolicyContextService(correspondence_repository=events,
        project_link_repository=links, requirement_repository=requirements,
        attachment_repository=attachments, lineage_repository=lineage)
    contexts = RequirementReconciliationContextService(project_link_repository=links,
        correspondence_repository=events, requirement_repository=requirements,
        attachment_repository=attachments, lineage_repository=lineage,
        max_requirements=100, max_attachments=20, max_source_characters=200_000)

    async def propose(project_index, subject, body, build, *, approve=False):
        project, contact = created_projects[project_index]
        event, link = correspondence(project, contact, subject, body, 1)
        proposal = build(RequirementSourceEvidence(correspondence_event_id=event.id, source_field="BODY", excerpt=body))
        proposed = await RequirementReconciliationService(agent=_PreparedProposal(proposal),
            lineage_repository=lineage, model_identifier="synthetic-authored/offline").reconcile(contexts.build(link.id))
        authorized = RequirementPolicyAuthorizationService(session=session, context_service=policy_context,
            lineage_repository=lineage, requirement_repository=requirements, follow_up_lifecycle_service=lifecycle).authorize(proposed.proposal.id)
        if authorized.evaluation.decision is PolicyDecision.REVIEW_REQUIRED:
            review = RequirementReviewCreationService(session=session, lineage_repository=lineage,
                requirement_repository=requirements, review_repository=reviews).ensure_review_for_policy_evaluation(authorized.evaluation.id).review_item
            if approve:
                RequirementReviewDecisionService(session=session, review_repository=reviews,
                    lineage_repository=lineage, requirement_repository=requirements,
                    context_service=policy_context, follow_up_lifecycle_service=lifecycle).approve(review.id, operator_subject=operator)
            return review.id
        if authorized.evaluation.decision is not PolicyDecision.ALLOW_AUTO_ACTION:
            raise ValueError("Authored synthetic proposal failed normal policy validation")
        return None

    joinery = created_requirements[0][0]
    await propose(0, "Alder Row — joinery drawing progress",
        "Hi Elena,\n\nThe reception desk drawings have been issued to the consultant. "
        "The retail display details are still being coordinated with the lighting supplier, so that part of the package remains open.\n\nRegards,\nPriya",
        lambda evidence: RequirementReconciliation(existing_impacts=(ExistingRequirementImpact(
            requirement_id=joinery.id, disposition="UPDATE_PROPOSED", proposed_state="PARTIAL",
            evidence=(evidence,), interpretation="Reception details issued; display details remain outstanding."),)))
    ventilation = created_requirements[1][0]
    replacement = ventilation.expected_date + timedelta(days=3)
    pending_id = await propose(1, "Westmere — balancing report submission",
        f"Hi Elena,\n\nThe balancing engineer needs one additional visit after the treatment-room ceilings are closed. "
        f"We propose submitting the signed report on {replacement.strftime('%d %B %Y')} instead. "
        "Please confirm whether this works with the consultant's inspection programme.\n\nKind regards,\nSofia",
        lambda evidence: RequirementReconciliation(existing_impacts=(ExistingRequirementImpact(
            requirement_id=ventilation.id, disposition="UPDATE_PROPOSED", proposed_expected_date=replacement,
            evidence=(evidence,), interpretation="The proposed delay affects the consultant inspection programme and needs approval."),)))
    certificates = created_requirements[2][0]
    corrected = today - timedelta(days=2)
    approved_id = await propose(2, "Brookfield — corrected certificate commitment",
        f"Hi Elena,\n\nPlease correct the commissioning-pack date in my earlier coordination note. "
        f"The agreed submission date was {corrected.strftime('%d %B %Y')}, not {certificates.expected_date.strftime('%d %B %Y')}. "
        "The consultant's signatures are still outstanding; I will send the complete pack once these are returned.\n\nBest regards,\nMarcus",
        lambda evidence: RequirementReconciliation(corrections=(RequirementCorrectionProposal(
            kind="CORRECTION", requirement_id=certificates.id, previous_state=RequirementState.OPEN,
            previous_expected_date=certificates.expected_date, proposed_expected_date=corrected,
            target_evidence_item_ids=(prior_evidence[2][0].id,), evidence=(evidence,),
            interpretation="Explicit replacement of the earlier submission date; the obligation remains outstanding."),)), approve=True)
    FollowUpDueService(session=session, follow_up_repository=follow_ups, audit_repository=lineage).process_due()
    session.commit()
    due = [item for item in follow_ups.list_actionable_due() if item.requirement_id == certificates.id]
    if len(due) != 1:
        raise ValueError("Synthetic correction must produce exactly one due correspondence-origin follow-up")
    eligibility = ReplyDraftEligibilityService(follow_up_repository=follow_ups, requirement_repository=requirements,
        lineage_repository=lineage, correspondence_repository=events, project_link_repository=links, contact_repository=contacts)
    scoped = ScopedReplyDraftContextService(eligibility_service=eligibility,
        follow_up_read_service=FollowUpReadService(follow_up_repository=follow_ups), project_repository=projects,
        requirement_repository=requirements, correspondence_repository=events, follow_up_repository=follow_ups,
        document_repository=documents, lineage_repository=lineage)
    draft = await ReplyDraftGenerationService(session=session, eligibility_service=eligibility,
        scoped_context_service=scoped, runner=ReplyDrafterRunner(agent=_PreparedReply(), model_identifier="synthetic-authored/offline"),
        grounding_validator=ReplyDraftGroundingValidator(lineage_repository=lineage, correspondence_repository=events,
            project_link_repository=links, document_repository=documents), follow_up_repository=follow_ups,
        requirement_repository=requirements, reply_draft_repository=ReplyDraftRepository(session),
        lineage_repository=lineage, project_contact_repository=contacts).generate(due[0].id)
    return {"project_ids": [str(item[0].id) for item in created_projects],
            "pending_review_id": str(pending_id), "approved_review_id": str(approved_id),
            "follow_up_id": str(due[0].id), "reply_draft_id": str(draft.reply_draft_id)}


def main() -> None:
    load_dotenv()
    settings = Settings()
    target = validate_target(settings, os.environ.get("TEST_DATABASE_URL"))
    engine = create_engine(target, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() != ["0011"]:
                raise ValueError("Seed requires the normal Alembic migrations through 0011; do not stamp")
            with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                result = asyncio.run(seed_portfolio(session))
                session.commit()
        print(json.dumps(result, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
