from uuid import UUID

from app.contracts.reply_draft_context import (
    FollowUpReplyScope,
    ReplyDraftEligibility,
    ReplyDraftEligibilityReason,
    ReplyDraftEligibilityStatus,
)
from app.models.enums import FollowUpStatus, TransitionStatus
from app.normalization.correspondence import normalize_email, normalize_source
from app.repositories.correspondence_event import CorrespondenceEventRepository
from app.repositories.correspondence_project_link import (
    CorrespondenceProjectLinkRepository,
)
from app.repositories.follow_up import FollowUpRepository
from app.repositories.lineage import LineageRepository
from app.repositories.project_contact import ProjectContactRepository
from app.repositories.requirement import RequirementRepository


class ReplyDraftEligibilityNotFoundError(LookupError):
    pass


class ReplyDraftEligibilityService:
    """Read-only S2 V1 eligibility and scope derivation for a FollowUp."""

    def __init__(
        self,
        *,
        follow_up_repository: FollowUpRepository,
        requirement_repository: RequirementRepository,
        lineage_repository: LineageRepository,
        correspondence_repository: CorrespondenceEventRepository,
        project_link_repository: CorrespondenceProjectLinkRepository,
        contact_repository: ProjectContactRepository,
    ) -> None:
        self.follow_ups = follow_up_repository
        self.requirements = requirement_repository
        self.lineage = lineage_repository
        self.correspondence = correspondence_repository
        self.project_links = project_link_repository
        self.contacts = contact_repository

    def assess(self, follow_up_id: UUID) -> ReplyDraftEligibility:
        follow_up = self.follow_ups.get(follow_up_id)
        if follow_up is None:
            raise ReplyDraftEligibilityNotFoundError("follow-up was not found")
        if follow_up.status is not FollowUpStatus.DUE:
            return self._ineligible(ReplyDraftEligibilityReason.FOLLOW_UP_NOT_DUE)

        requirement = self.requirements.get(follow_up.requirement_id)
        if requirement is None or requirement.project_id != follow_up.project_id:
            return self._ineligible(ReplyDraftEligibilityReason.INCONSISTENT_LINEAGE)

        correspondence_event_id, origin_reason = self._source_from_origin(follow_up)
        if origin_reason is not None:
            return self._ineligible(origin_reason)
        assert correspondence_event_id is not None

        correspondence = self.correspondence.get(correspondence_event_id)
        if correspondence is None:
            return self._ineligible(
                ReplyDraftEligibilityReason.MISSING_SOURCE_CORRESPONDENCE
            )
        if self.project_links.get_approved_link(
            correspondence_event_id=correspondence.id,
            project_id=follow_up.project_id,
        ) is None:
            approved_project_ids = (
                self.project_links.list_approved_project_ids_for_event(
                    correspondence.id
                )
            )
            return self._ineligible(
                (
                    ReplyDraftEligibilityReason.SOURCE_PROJECT_MISMATCH
                    if approved_project_ids
                    else ReplyDraftEligibilityReason.NO_AUTHORITATIVE_PROJECT_LINK
                )
            )
        if normalize_source(correspondence.source) != "gmail":
            return self._ineligible(ReplyDraftEligibilityReason.UNSUPPORTED_SOURCE)
        if not correspondence.external_event_id.strip() or not (
            correspondence.external_conversation_id
            and correspondence.external_conversation_id.strip()
        ):
            return self._ineligible(
                ReplyDraftEligibilityReason.MISSING_GMAIL_SOURCE_METADATA
            )

        sender_email = normalize_email(correspondence.sender_email or "")
        if not sender_email:
            return self._ineligible(
                ReplyDraftEligibilityReason.SENDER_NOT_ACTIVE_TRUSTED_CONTACT
            )
        contact = self.contacts.get_active_for_project_email(
            project_id=follow_up.project_id,
            email_normalized=sender_email,
        )
        if (
            contact is None
            or contact.project_id != follow_up.project_id
            or not contact.is_active
        ):
            return self._ineligible(
                ReplyDraftEligibilityReason.SENDER_NOT_ACTIVE_TRUSTED_CONTACT
            )

        return ReplyDraftEligibility(
            status=ReplyDraftEligibilityStatus.DRAFTABLE,
            scope=FollowUpReplyScope(
                follow_up_id=follow_up.id,
                project_id=follow_up.project_id,
                requirement_id=follow_up.requirement_id,
                source_correspondence_event_id=correspondence.id,
                trusted_contact_id=contact.id,
                gmail_message_id=correspondence.external_event_id,
                gmail_thread_id=correspondence.external_conversation_id,
                originating_state_transition_id=(
                    follow_up.originating_state_transition_id
                ),
                originating_audit_event_id=follow_up.originating_audit_event_id,
            ),
        )

    def _source_from_origin(self, follow_up) -> tuple[
        UUID | None, ReplyDraftEligibilityReason | None
    ]:
        transition_id = follow_up.originating_state_transition_id
        audit_id = follow_up.originating_audit_event_id
        if (transition_id is None) == (audit_id is None):
            return None, ReplyDraftEligibilityReason.MISSING_AUTHORITATIVE_LINEAGE
        if transition_id is not None:
            transition = self.lineage.get_state_transition_by_id(transition_id)
            if transition is None or transition.status is not TransitionStatus.APPLIED:
                return None, ReplyDraftEligibilityReason.MISSING_AUTHORITATIVE_LINEAGE
            proposal = self.lineage.get_proposal(transition.ai_proposal_id)
            if proposal is None or proposal.id != transition.ai_proposal_id:
                return None, ReplyDraftEligibilityReason.MISSING_AUTHORITATIVE_LINEAGE
            return proposal.correspondence_event_id, None

        audit = self.lineage.get_audit_event_by_id(audit_id)
        if audit is None:
            return None, ReplyDraftEligibilityReason.MISSING_AUTHORITATIVE_LINEAGE
        if (
            (audit.project_id is not None and audit.project_id != follow_up.project_id)
            or (
                audit.requirement_id is not None
                and audit.requirement_id != follow_up.requirement_id
            )
        ):
            return None, ReplyDraftEligibilityReason.INCONSISTENT_LINEAGE
        if audit.correspondence_event_id is None:
            return None, ReplyDraftEligibilityReason.MISSING_SOURCE_CORRESPONDENCE
        return audit.correspondence_event_id, None

    @staticmethod
    def _ineligible(reason: ReplyDraftEligibilityReason) -> ReplyDraftEligibility:
        return ReplyDraftEligibility(
            status=ReplyDraftEligibilityStatus.NOT_DRAFTABLE_IN_S2_V1,
            reason=reason,
        )
