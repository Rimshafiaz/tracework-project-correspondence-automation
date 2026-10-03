from dataclasses import dataclass
from uuid import UUID

from app.ai.schemas import CandidateSignalReference, ResolutionConcern, ResolutionStatus
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSignal
from app.contracts.project_identity_policy import ProjectIdentityPolicyContext, ProjectIdentityPolicyResult, ProjectIdentityRule
from app.models.enums import PolicyDecision, ProposalType
from app.services.policy.project_identity_rules import PROJECT_IDENTITY_POLICY_VERSION, reason_for_project_identity_rule


@dataclass(frozen=True)
class _CandidateFacts:
    observation_rules: tuple[ProjectIdentityRule, ...]
    weak_rules: tuple[ProjectIdentityRule, ...]
    has_approved_conversation: bool
    has_project_code: bool
    has_verified_identifier: bool
    has_document_identifier: bool
    has_known_contact: bool
    has_unverified_authorization_signal: bool


def reject_missing_candidate_snapshot(
    *,
    proposal_id: UUID,
    resolver_status: ResolutionStatus,
) -> ProjectIdentityPolicyResult:
    return _result(
        proposal_id=proposal_id,
        resolver_status=resolver_status,
        decision=PolicyDecision.REJECT_PROPOSAL,
        rules=(ProjectIdentityRule.CANDIDATE_SNAPSHOT_MISSING,),
    )


def evaluate_project_identity(
    context: ProjectIdentityPolicyContext,
) -> ProjectIdentityPolicyResult:
    if context.proposal_type is not ProposalType.PROJECT_RESOLUTION:
        return _result_for_context(
            context,
            PolicyDecision.REJECT_PROPOSAL,
            (ProjectIdentityRule.PROPOSAL_TYPE_INVALID,),
        )

    if not _resolution_matches_candidates(context):
        return _result_for_context(
            context,
            PolicyDecision.REJECT_PROPOSAL,
            (ProjectIdentityRule.RESOLUTION_INTEGRITY_FAILED,),
        )

    if _required_evidence_is_invalid(context):
        return _result_for_context(
            context,
            PolicyDecision.REJECT_PROPOSAL,
            (ProjectIdentityRule.EVIDENCE_NOT_CURRENTLY_VALID,),
        )

    resolution = context.resolution
    if resolution.status is ResolutionStatus.NO_MATCH:
        return _result_for_context(
            context,
            PolicyDecision.REVIEW_REQUIRED,
            (ProjectIdentityRule.NO_MATCH,),
        )

    conflict_rules = _detect_conflicts(context)
    resolver_rules = []
    if resolution.status is ResolutionStatus.REVIEW_REQUIRED:
        resolver_rules.append(ProjectIdentityRule.RESOLVER_REVIEW_REQUIRED)
    if resolution.conflicts or ResolutionConcern.CONFLICTING_EVIDENCE in resolution.concerns:
        resolver_rules.append(ProjectIdentityRule.RESOLVER_REPORTED_CONFLICT)
    if conflict_rules or resolver_rules:
        return _result_for_context(
            context,
            PolicyDecision.REVIEW_REQUIRED,
            _unique_rules((*resolver_rules, *conflict_rules)),
        )

    if (
        resolution.status is ResolutionStatus.MULTI_PROJECT
        and ResolutionConcern.MULTI_PROJECT_SCOPE_UNCLEAR in resolution.concerns
    ):
        return _result_for_context(
            context,
            PolicyDecision.REVIEW_REQUIRED,
            (ProjectIdentityRule.MULTI_PROJECT_SCOPE_UNCLEAR,),
        )

    candidates = {candidate.project_id: candidate for candidate in context.candidate_set.candidates}
    facts_by_project = {
        project_id: _candidate_facts(context, candidates[project_id])
        for project_id in resolution.project_ids
    }

    project_rules = {
        project_id: _automatic_rules(facts)
        for project_id, facts in facts_by_project.items()
    }
    if any(
        facts.has_unverified_authorization_signal and not project_rules[project_id]
        for project_id, facts in facts_by_project.items()
    ):
        return _result_for_context(
            context,
            PolicyDecision.REJECT_PROPOSAL,
            (ProjectIdentityRule.PROVENANCE_UNVERIFIED,),
        )
    if resolution.status is ResolutionStatus.MULTI_PROJECT:
        if not _has_separately_scoped_evidence(context):
            return _result_for_context(
                context,
                PolicyDecision.REVIEW_REQUIRED,
                (ProjectIdentityRule.MULTI_PROJECT_EVIDENCE_INCOMPLETE,),
            )
        if all(project_rules.values()):
            rules = _unique_rules(
                tuple(
                    rule
                    for facts in facts_by_project.values()
                    for rule in facts.observation_rules
                )
                + tuple(rule for rules in project_rules.values() for rule in rules)
                + (ProjectIdentityRule.MULTI_PROJECT_AUTO_ELIGIBLE,)
            )
            return _result_for_context(
                context,
                PolicyDecision.ALLOW_AUTO_ACTION,
                rules,
            )
        rules = _unique_rules(
            tuple(
                rule
                for facts in facts_by_project.values()
                for rule in (*facts.observation_rules, *facts.weak_rules)
            )
            + (ProjectIdentityRule.MULTI_PROJECT_PARTIAL_TRUST,)
        )
        return _result_for_context(
            context,
            PolicyDecision.REVIEW_REQUIRED,
            rules,
        )

    project_id = resolution.project_ids[0]
    facts = facts_by_project[project_id]
    automatic_rules = project_rules[project_id]
    if automatic_rules:
        return _result_for_context(
            context,
            PolicyDecision.ALLOW_AUTO_ACTION,
            _unique_rules((*facts.observation_rules, *automatic_rules)),
        )

    insufficient_rules = list(facts.observation_rules)
    insufficient_rules.extend(facts.weak_rules)
    if facts.has_known_contact and not (
        facts.has_project_code
        or facts.has_verified_identifier
        or facts.has_document_identifier
    ):
        insufficient_rules.append(ProjectIdentityRule.KNOWN_CONTACT_ONLY)
    if not facts.has_known_contact and not facts.has_approved_conversation:
        insufficient_rules.append(ProjectIdentityRule.UNKNOWN_OR_UNTRUSTED_SENDER)
    if not facts.observation_rules and not facts.weak_rules:
        insufficient_rules.append(ProjectIdentityRule.SEMANTIC_INTERPRETATION_ONLY)
    insufficient_rules.append(ProjectIdentityRule.INSUFFICIENT_INDEPENDENT_IDENTITY)
    return _result_for_context(
        context,
        PolicyDecision.REVIEW_REQUIRED,
        _unique_rules(tuple(insufficient_rules)),
    )


def _resolution_matches_candidates(context: ProjectIdentityPolicyContext) -> bool:
    candidates = {candidate.project_id: candidate for candidate in context.candidate_set.candidates}
    if not set(context.resolution.project_ids).issubset(candidates):
        return False
    for item in (*context.resolution.evidence, *context.resolution.conflicts):
        if any(
            reference.project_id not in candidates
            or not any(
                _matches_signal(reference, signal)
                for signal in candidates[reference.project_id].signals
            )
            for reference in item.signal_references
        ):
            return False
        if any(
            evidence.correspondence_event_id != context.correspondence_event_id
            for evidence in item.source_evidence
        ):
            return False
    return True


def _required_evidence_is_invalid(context: ProjectIdentityPolicyContext) -> bool:
    invalidated = set(context.invalidated_evidence_ids)
    if invalidated.intersection(context.proposal_evidence_ids):
        return True
    return any(
        reference.evidence_item_id in invalidated
        for item in (*context.resolution.evidence, *context.resolution.conflicts)
        for reference in item.signal_references
        if reference.evidence_item_id is not None
    )


def _candidate_facts(
    context: ProjectIdentityPolicyContext,
    candidate: ProjectCandidate,
) -> _CandidateFacts:
    valid_source_records = set(context.validated_source_record_ids)
    invalidated_evidence = set(context.invalidated_evidence_ids)
    observations = []
    weak = []
    approved_conversation = project_code = verified_identifier = False
    document_identifier = known_contact = unverified = False

    for signal in candidate.signals:
        signal_valid = _signal_provenance_is_valid(
            signal,
            valid_source_records,
            invalidated_evidence,
        )
        if signal.signal_type is CandidateSignalType.APPROVED_CONVERSATION:
            if signal_valid:
                approved_conversation = True
                observations.append(ProjectIdentityRule.APPROVED_CONVERSATION_LINK)
            else:
                unverified = True
        elif signal.signal_type is CandidateSignalType.PROJECT_CODE:
            if signal_valid:
                project_code = True
                observations.append(ProjectIdentityRule.EXACT_PROJECT_CODE)
            else:
                unverified = True
        elif signal.signal_type is CandidateSignalType.VERIFIED_IDENTIFIER:
            if signal_valid and signal.verified and signal.identifier_type:
                verified_identifier = True
                observations.append(ProjectIdentityRule.EXACT_VERIFIED_IDENTIFIER)
            else:
                unverified = True
        elif signal.signal_type is CandidateSignalType.DOCUMENT_IDENTIFIER:
            if signal_valid and signal.verified and signal.identifier_type:
                document_identifier = True
                observations.append(ProjectIdentityRule.EXACT_DOCUMENT_IDENTIFIER)
            else:
                unverified = True
        elif signal.signal_type is CandidateSignalType.PROJECT_CONTACT:
            if signal_valid:
                known_contact = True
                observations.append(ProjectIdentityRule.KNOWN_PROJECT_CONTACT)
            else:
                unverified = True
        elif signal.signal_type is CandidateSignalType.NORMALIZED_NAME:
            weak.append(ProjectIdentityRule.NORMALIZED_NAME_ONLY)
        elif signal.signal_type is CandidateSignalType.ALIAS:
            weak.append(ProjectIdentityRule.ALIAS_ONLY)
        elif signal.signal_type in {
            CandidateSignalType.FUZZY_NAME,
            CandidateSignalType.FUZZY_ALIAS,
        }:
            weak.append(ProjectIdentityRule.FUZZY_MATCH_ONLY)

    return _CandidateFacts(
        observation_rules=_unique_rules(tuple(observations)),
        weak_rules=_unique_rules(tuple(weak)),
        has_approved_conversation=approved_conversation,
        has_project_code=project_code,
        has_verified_identifier=verified_identifier,
        has_document_identifier=document_identifier,
        has_known_contact=known_contact,
        has_unverified_authorization_signal=unverified,
    )


def _signal_provenance_is_valid(
    signal: ProjectCandidateSignal,
    valid_source_record_ids: set[UUID],
    invalidated_evidence_ids: set[UUID],
) -> bool:
    if signal.evidence_item_id in invalidated_evidence_ids:
        return False
    if signal.source is CandidateSignalSource.ATTACHMENT and signal.attachment_id is None:
        return False
    if signal.source is CandidateSignalSource.EVIDENCE_ITEM and signal.evidence_item_id is None:
        return False
    if signal.signal_type in {
        CandidateSignalType.VERIFIED_IDENTIFIER,
        CandidateSignalType.DOCUMENT_IDENTIFIER,
        CandidateSignalType.PROJECT_CONTACT,
        CandidateSignalType.APPROVED_CONVERSATION,
    }:
        return (
            signal.source_record_id is not None
            and signal.source_record_id in valid_source_record_ids
        )
    return signal.exact


def _automatic_rules(facts: _CandidateFacts) -> tuple[ProjectIdentityRule, ...]:
    if facts.has_approved_conversation:
        return (ProjectIdentityRule.AUTO_APPROVED_CONVERSATION,)
    if facts.has_project_code and facts.has_known_contact:
        return (ProjectIdentityRule.AUTO_PROJECT_CODE_AND_CONTACT,)
    if (
        facts.has_verified_identifier or facts.has_document_identifier
    ) and facts.has_known_contact:
        return (ProjectIdentityRule.AUTO_VERIFIED_IDENTIFIER_AND_CONTACT,)
    return ()


def _detect_conflicts(
    context: ProjectIdentityPolicyContext,
) -> tuple[ProjectIdentityRule, ...]:
    signals = tuple(
        (candidate.project_id, signal)
        for candidate in context.candidate_set.candidates
        for signal in candidate.signals
        if signal.signal_type
        in {
            CandidateSignalType.PROJECT_CODE,
            CandidateSignalType.VERIFIED_IDENTIFIER,
            CandidateSignalType.DOCUMENT_IDENTIFIER,
            CandidateSignalType.APPROVED_CONVERSATION,
        }
    )
    rules = []
    identifiers = tuple(
        (project_id, signal)
        for project_id, signal in signals
        if signal.signal_type
        in {
            CandidateSignalType.VERIFIED_IDENTIFIER,
            CandidateSignalType.DOCUMENT_IDENTIFIER,
        }
        and signal.identifier_type is not None
    )

    by_type: dict[str, set[tuple[UUID, str]]] = {}
    by_identity: dict[tuple[str, str], set[UUID]] = {}
    for project_id, signal in identifiers:
        identifier_type = signal.identifier_type.casefold()
        value = signal.matched_value.casefold()
        by_type.setdefault(identifier_type, set()).add((project_id, value))
        by_identity.setdefault((identifier_type, value), set()).add(project_id)
    if any(
        len({project_id for project_id, _ in entries}) > 1
        and len({value for _, value in entries}) > 1
        for entries in by_type.values()
    ):
        rules.append(ProjectIdentityRule.SAME_TYPE_DIFFERENT_VALUES)
    if any(len(project_ids) > 1 for project_ids in by_identity.values()):
        rules.append(ProjectIdentityRule.SAME_IDENTIFIER_MULTIPLE_PROJECTS)

    body_projects = {
        project_id
        for project_id, signal in signals
        if signal.source is CandidateSignalSource.CORRESPONDENCE_EVENT
        and signal.signal_type is not CandidateSignalType.APPROVED_CONVERSATION
    }
    document_projects = {
        project_id
        for project_id, signal in signals
        if signal.source in {
            CandidateSignalSource.ATTACHMENT,
            CandidateSignalSource.EVIDENCE_ITEM,
        }
        or signal.signal_type is CandidateSignalType.DOCUMENT_IDENTIFIER
    }
    if any(body != document for body in body_projects for document in document_projects):
        rules.append(ProjectIdentityRule.BODY_ATTACHMENT_IDENTITY_CONFLICT)

    conversation_projects = {
        project_id
        for project_id, signal in signals
        if signal.signal_type is CandidateSignalType.APPROVED_CONVERSATION
    }
    current_identity_projects = {
        project_id
        for project_id, signal in signals
        if signal.signal_type
        in {
            CandidateSignalType.PROJECT_CODE,
            CandidateSignalType.VERIFIED_IDENTIFIER,
            CandidateSignalType.DOCUMENT_IDENTIFIER,
        }
    }
    if any(
        conversation != current
        for conversation in conversation_projects
        for current in current_identity_projects
    ):
        rules.append(ProjectIdentityRule.CONVERSATION_IDENTIFIER_CONFLICT)
    return _unique_rules(tuple(rules))


def _has_separately_scoped_evidence(context: ProjectIdentityPolicyContext) -> bool:
    evidenced_projects = {item.project_id for item in context.resolution.evidence}
    return set(context.resolution.project_ids) == evidenced_projects


def _matches_signal(
    reference: CandidateSignalReference,
    signal: ProjectCandidateSignal,
) -> bool:
    return (
        reference.signal_type is signal.signal_type
        and reference.matched_value == signal.matched_value
        and reference.source is signal.source
        and reference.identifier_type == signal.identifier_type
        and reference.source_record_id == signal.source_record_id
        and reference.attachment_id == signal.attachment_id
        and reference.evidence_item_id == signal.evidence_item_id
    )


def _result_for_context(
    context: ProjectIdentityPolicyContext,
    decision: PolicyDecision,
    rules: tuple[ProjectIdentityRule, ...],
) -> ProjectIdentityPolicyResult:
    invalidated = set(context.invalidated_evidence_ids)
    return _result(
        proposal_id=context.proposal_id,
        resolver_status=context.resolution.status,
        decision=decision,
        rules=rules,
        evidence_ids=tuple(
            evidence_id
            for evidence_id in context.proposal_evidence_ids
            if evidence_id not in invalidated
        ),
    )


def _result(
    *,
    proposal_id: UUID,
    resolver_status: ResolutionStatus,
    decision: PolicyDecision,
    rules: tuple[ProjectIdentityRule, ...],
    evidence_ids: tuple[UUID, ...] = (),
) -> ProjectIdentityPolicyResult:
    rules = _unique_rules(rules)
    return ProjectIdentityPolicyResult(
        proposal_id=proposal_id,
        resolver_status=resolver_status,
        policy_version=PROJECT_IDENTITY_POLICY_VERSION,
        decision=decision,
        triggered_rule_ids=rules,
        reasons=tuple(reason_for_project_identity_rule(rule) for rule in rules),
        evidence_ids=evidence_ids,
    )


def _unique_rules(
    rules: tuple[ProjectIdentityRule, ...],
) -> tuple[ProjectIdentityRule, ...]:
    return tuple(dict.fromkeys(rules))
