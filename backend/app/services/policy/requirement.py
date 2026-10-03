from dataclasses import dataclass
from uuid import UUID

from app.ai.requirement_schemas import ExistingEvidenceReference, RequirementEvidenceReference, RequirementImpactDisposition, RequirementReconciliationConcernType, RequirementSourceEvidence
from app.contracts.requirement_policy import NewRequirementPolicyResult, RequirementPolicyContext, RequirementPolicyEvidenceFact, RequirementPolicyResult, RequirementPolicyRule, RequirementTransitionEffect
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType, RequirementState
from app.services.policy.requirement_rules import REQUIREMENT_POLICY_VERSION, reason_for_requirement_policy_rule


@dataclass(frozen=True)
class _EvidenceResolution:
    impact_evidence: dict[UUID, tuple[UUID, ...]]
    unscoped_impact_ids: frozenset[UUID]
    new_requirement_evidence: dict[int, tuple[UUID, ...]]
    all_evidence_ids: tuple[UUID, ...]


class _IntegrityFailure(ValueError):
    def __init__(self, rule: RequirementPolicyRule) -> None:
        super().__init__(reason_for_requirement_policy_rule(rule))
        self.rule = rule


def reject_requirement_policy_context_failure(
    *,
    proposal_id: UUID,
    rule: RequirementPolicyRule,
) -> RequirementPolicyResult:
    return _result(
        proposal_id=proposal_id,
        decision=PolicyDecision.REJECT_PROPOSAL,
        rules=(rule,),
    )


def evaluate_requirement_policy(
    context: RequirementPolicyContext,
) -> RequirementPolicyResult:
    if context.proposal_type is not ProposalType.REQUIREMENT_RECONCILIATION:
        return reject_requirement_policy_context_failure(
            proposal_id=context.proposal_id,
            rule=RequirementPolicyRule.PROPOSAL_TYPE_INVALID,
        )

    integrity_rule = _basic_integrity_failure(context)
    if integrity_rule is not None:
        return reject_requirement_policy_context_failure(
            proposal_id=context.proposal_id,
            rule=integrity_rule,
        )

    try:
        evidence = _resolve_evidence(context)
    except _IntegrityFailure as exc:
        return reject_requirement_policy_context_failure(
            proposal_id=context.proposal_id,
            rule=exc.rule,
        )

    stale_rules = _stale_rules(context)
    semantic_rules = _semantic_review_rules(context)
    snapshot_requirements = {
        item.requirement_id: item for item in context.m11_snapshot.requirements
    }
    current_requirements = {
        item.requirement_id: item for item in context.current_requirements
    }
    effects = []
    for impact in context.reconciliation.existing_impacts:
        if impact.disposition is RequirementImpactDisposition.NO_CHANGE:
            continue
        observed = snapshot_requirements[impact.requirement_id]
        current = current_requirements[impact.requirement_id]
        proposed_state = impact.proposed_state or observed.current_state
        proposed_expected_date = (
            impact.proposed_expected_date
            if impact.proposed_expected_date is not None
            else observed.expected_date
        )
        rules = list(stale_rules)
        rules.extend(semantic_rules)
        if impact.requirement_id in evidence.unscoped_impact_ids:
            rules.append(RequirementPolicyRule.INSUFFICIENT_SCOPED_EVIDENCE)
        rules.extend(
            _transition_rules(
                current_state=current.state,
                proposed_state=proposed_state,
                current_expected_date=current.expected_date,
                proposed_expected_date=proposed_expected_date,
            )
        )
        rules = list(_unique_rules(tuple(rules)))
        if not rules:
            rules.extend(
                (
                    RequirementPolicyRule.OPEN_TO_PARTIAL,
                    RequirementPolicyRule.AUTO_ELIGIBLE,
                )
            )
        effect_decision = (
            PolicyDecision.REVIEW_REQUIRED
            if any(_rule_requires_review(rule) for rule in rules)
            else PolicyDecision.ALLOW_AUTO_ACTION
        )
        effects.append(
            RequirementTransitionEffect(
                requirement_id=impact.requirement_id,
                observed_state=observed.current_state,
                observed_expected_date=observed.expected_date,
                current_state=current.state,
                current_expected_date=current.expected_date,
                proposed_state=proposed_state,
                proposed_expected_date=proposed_expected_date,
                decision=effect_decision,
                triggered_rule_ids=tuple(rules),
                reasons=tuple(reason_for_requirement_policy_rule(rule) for rule in rules),
                evidence_ids=evidence.impact_evidence[impact.requirement_id],
            )
        )

    new_results = tuple(
        NewRequirementPolicyResult(
            proposal_index=index,
            decision=PolicyDecision.REVIEW_REQUIRED,
            triggered_rule_ids=_new_requirement_rules(context),
            reasons=tuple(
                reason_for_requirement_policy_rule(rule)
                for rule in _new_requirement_rules(context)
            ),
            evidence_ids=evidence.new_requirement_evidence[index],
        )
        for index, _proposal in enumerate(context.reconciliation.new_requirements)
    )

    overall_rules = list(stale_rules)
    overall_rules.extend(semantic_rules)
    overall_rules.extend(
        rule for effect in effects for rule in effect.triggered_rule_ids
    )
    overall_rules.extend(
        rule for result in new_results for rule in result.triggered_rule_ids
    )
    actionable_count = len(effects) + len(new_results)
    any_review = (
        bool(stale_rules or semantic_rules or new_results)
        or any(effect.decision is PolicyDecision.REVIEW_REQUIRED for effect in effects)
    )
    if any_review and actionable_count > 1:
        overall_rules.append(RequirementPolicyRule.MULTI_IMPACT_ATOMIC_REVIEW)
    if not overall_rules:
        overall_rules.append(RequirementPolicyRule.NO_CHANGE)
    overall_rules = list(_unique_rules(tuple(overall_rules)))
    return _result(
        proposal_id=context.proposal_id,
        decision=(
            PolicyDecision.REVIEW_REQUIRED
            if any_review
            else PolicyDecision.ALLOW_AUTO_ACTION
        ),
        rules=tuple(overall_rules),
        effects=tuple(effects),
        new_results=new_results,
        evidence_ids=evidence.all_evidence_ids,
    )


def _basic_integrity_failure(
    context: RequirementPolicyContext,
) -> RequirementPolicyRule | None:
    snapshot = context.m11_snapshot
    if (
        snapshot.correspondence_event_id != context.correspondence_event_id
        or snapshot.project_id is None
    ):
        return RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED
    link = context.authoritative_project_link
    if (
        link is None
        or link.link_id != snapshot.authoritative_project_link_id
        or link.correspondence_event_id != context.correspondence_event_id
        or link.project_id != snapshot.project_id
    ):
        return RequirementPolicyRule.PROJECT_LINK_INVALID

    snapshot_ids = {item.requirement_id for item in snapshot.requirements}
    current_by_id = {
        item.requirement_id: item for item in context.current_requirements
    }
    referenced_ids = {
        impact.requirement_id
        for impact in context.reconciliation.existing_impacts
    }
    referenced_ids.update(
        requirement_id
        for concern in context.reconciliation.concerns
        for requirement_id in concern.candidate_requirement_ids
    )
    referenced_ids.update(
        requirement_id
        for conflict in context.reconciliation.conflicts
        for requirement_id in conflict.requirement_ids
    )
    if not referenced_ids.issubset(snapshot_ids):
        return RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED
    if not snapshot_ids.issubset(current_by_id):
        return RequirementPolicyRule.REQUIREMENT_NOT_CURRENT
    if any(
        current_by_id[requirement_id].project_id != snapshot.project_id
        for requirement_id in snapshot_ids
    ):
        return RequirementPolicyRule.REQUIREMENT_NOT_CURRENT
    return None


def _resolve_evidence(context: RequirementPolicyContext) -> _EvidenceResolution:
    facts = {item.evidence_item_id: item for item in context.proposal_evidence}
    impact_evidence = {}
    unscoped = set()
    referenced_ids = []
    for impact in context.reconciliation.existing_impacts:
        ids = []
        for reference in impact.evidence:
            fact = _resolve_reference(
                reference,
                tuple(facts.values()),
                expected_requirement_id=impact.requirement_id,
            )
            _validate_evidence_fact(
                fact,
                project_id=context.m11_snapshot.project_id,
                expected_requirement_id=impact.requirement_id,
                source_reference=reference if isinstance(reference, RequirementSourceEvidence) else None,
            )
            if fact.requirement_id is None:
                unscoped.add(impact.requirement_id)
            ids.append(fact.evidence_item_id)
            referenced_ids.append(fact.evidence_item_id)
        if impact.disposition is RequirementImpactDisposition.UPDATE_PROPOSED and not ids:
            raise _IntegrityFailure(RequirementPolicyRule.EVIDENCE_MISSING_OR_UNLINKED)
        impact_evidence[impact.requirement_id] = tuple(dict.fromkeys(ids))

    new_evidence = {}
    for index, proposal in enumerate(context.reconciliation.new_requirements):
        ids = []
        for reference in proposal.evidence:
            fact = _resolve_reference(reference, tuple(facts.values()))
            _validate_evidence_fact(
                fact,
                project_id=context.m11_snapshot.project_id,
                source_reference=reference if isinstance(reference, RequirementSourceEvidence) else None,
            )
            ids.append(fact.evidence_item_id)
            referenced_ids.append(fact.evidence_item_id)
        new_evidence[index] = tuple(dict.fromkeys(ids))

    for item in (*context.reconciliation.concerns, *context.reconciliation.conflicts):
        for reference in item.evidence:
            fact = _resolve_reference(reference, tuple(facts.values()))
            _validate_evidence_fact(
                fact,
                project_id=context.m11_snapshot.project_id,
                source_reference=reference if isinstance(reference, RequirementSourceEvidence) else None,
            )
            referenced_ids.append(fact.evidence_item_id)

    referenced = set(referenced_ids)
    if referenced != set(facts):
        raise _IntegrityFailure(RequirementPolicyRule.EVIDENCE_MISSING_OR_UNLINKED)
    return _EvidenceResolution(
        impact_evidence=impact_evidence,
        unscoped_impact_ids=frozenset(unscoped),
        new_requirement_evidence=new_evidence,
        all_evidence_ids=tuple(dict.fromkeys(referenced_ids)),
    )


def _resolve_reference(
    reference: RequirementEvidenceReference,
    facts: tuple[RequirementPolicyEvidenceFact, ...],
    expected_requirement_id: UUID | None = None,
) -> RequirementPolicyEvidenceFact:
    if isinstance(reference, ExistingEvidenceReference):
        matches = [
            fact for fact in facts
            if fact.evidence_item_id == reference.evidence_item_id
        ]
    else:
        matches = [
            fact
            for fact in facts
            if fact.correspondence_event_id == reference.correspondence_event_id
            and fact.attachment_id == reference.attachment_id
            and fact.source_type == reference.source_field.value.lower()
            and fact.excerpt == reference.excerpt
        ]
        scoped_matches = [
            fact
            for fact in matches
            if fact.requirement_id == expected_requirement_id
        ]
        if len(scoped_matches) == 1:
            matches = scoped_matches
    if len(matches) != 1:
        raise _IntegrityFailure(RequirementPolicyRule.EVIDENCE_MISSING_OR_UNLINKED)
    return matches[0]


def _validate_evidence_fact(
    fact: RequirementPolicyEvidenceFact,
    *,
    project_id: UUID,
    expected_requirement_id: UUID | None = None,
    source_reference: RequirementSourceEvidence | None = None,
) -> None:
    if fact.validity is not EvidenceValidity.VALID:
        raise _IntegrityFailure(RequirementPolicyRule.EVIDENCE_INVALIDATED)
    if fact.project_id != project_id:
        raise _IntegrityFailure(RequirementPolicyRule.EVIDENCE_SCOPE_MISMATCH)
    if (
        expected_requirement_id is not None
        and fact.requirement_id not in {None, expected_requirement_id}
    ):
        raise _IntegrityFailure(RequirementPolicyRule.EVIDENCE_SCOPE_MISMATCH)
    if source_reference is None:
        return
    metadata = fact.provenance_metadata or {}
    start = metadata.get("start_offset")
    end = metadata.get("end_offset")
    if (
        metadata.get("source_field") != source_reference.source_field.value
        or not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end - start != len(source_reference.excerpt)
    ):
        raise _IntegrityFailure(RequirementPolicyRule.PROVENANCE_INTEGRITY_FAILED)


def _stale_rules(
    context: RequirementPolicyContext,
) -> tuple[RequirementPolicyRule, ...]:
    snapshot = context.m11_snapshot
    rules = []
    snapshot_by_id = {item.requirement_id: item for item in snapshot.requirements}
    current_by_id = {
        item.requirement_id: item for item in context.current_requirements
    }
    if set(snapshot_by_id) != set(current_by_id):
        rules.append(RequirementPolicyRule.REQUIREMENT_SET_STALE)
    for requirement_id, observed in snapshot_by_id.items():
        current = current_by_id[requirement_id]
        if current.state is not observed.current_state:
            rules.append(RequirementPolicyRule.REQUIREMENT_STATE_STALE)
        if current.expected_date != observed.expected_date:
            rules.append(RequirementPolicyRule.EXPECTED_DATE_STALE)
        if (
            current.name != observed.name
            or current.description != observed.description
        ):
            rules.append(RequirementPolicyRule.REQUIREMENT_DEFINITION_STALE)
    if (
        context.current_subject_sha256 != snapshot.subject_sha256
        or context.current_body_sha256 != snapshot.body_sha256
        or set(context.current_attachments) != set(snapshot.attachments)
        or {
            (
                item.evidence_item_id,
                item.project_id,
                item.requirement_id,
                item.validity,
                item.excerpt_sha256,
            )
            for item in context.current_snapshot_evidence
        }
        != {
            (
                item.evidence_item_id,
                item.project_id,
                item.requirement_id,
                item.validity,
                item.excerpt_sha256,
            )
            for item in snapshot.existing_evidence
        }
    ):
        rules.append(RequirementPolicyRule.SOURCE_CONTEXT_STALE)
    return _unique_rules(tuple(rules))


def _semantic_review_rules(
    context: RequirementPolicyContext,
) -> tuple[RequirementPolicyRule, ...]:
    rules = []
    if context.reconciliation.concerns:
        rules.append(RequirementPolicyRule.M11_CONCERN)
    if any(
        concern.concern_type is RequirementReconciliationConcernType.POSSIBLE_DUPLICATE_REQUIREMENT
        for concern in context.reconciliation.concerns
    ):
        rules.append(RequirementPolicyRule.POSSIBLE_DUPLICATE)
    if context.reconciliation.conflicts:
        rules.append(RequirementPolicyRule.M11_CONFLICT)
    return tuple(rules)


def _transition_rules(
    *,
    current_state: RequirementState,
    proposed_state: RequirementState,
    current_expected_date,
    proposed_expected_date,
) -> tuple[RequirementPolicyRule, ...]:
    rules = []
    if proposed_expected_date != current_expected_date:
        rules.append(RequirementPolicyRule.EXPECTED_DATE_REQUIRES_REVIEW)
    if proposed_state is RequirementState.SATISFIED:
        rules.append(RequirementPolicyRule.SATISFIED_REQUIRES_REVIEW)
    if current_state is RequirementState.REVIEW or proposed_state is RequirementState.REVIEW:
        rules.append(RequirementPolicyRule.REVIEW_STATE_TRANSITION)
    rank = {
        RequirementState.OPEN: 0,
        RequirementState.PARTIAL: 1,
        RequirementState.SATISFIED: 2,
    }
    if (
        current_state in rank
        and proposed_state in rank
        and rank[proposed_state] < rank[current_state]
    ):
        rules.append(RequirementPolicyRule.BACKWARD_TRANSITION)
    if (
        proposed_state is not current_state
        and not (
            current_state is RequirementState.OPEN
            and proposed_state is RequirementState.PARTIAL
        )
        and not rules
    ):
        rules.append(RequirementPolicyRule.REVIEW_STATE_TRANSITION)
    return _unique_rules(tuple(rules))


def _new_requirement_rules(
    context: RequirementPolicyContext,
) -> tuple[RequirementPolicyRule, ...]:
    rules = [RequirementPolicyRule.NEW_REQUIREMENT]
    if any(
        concern.concern_type is RequirementReconciliationConcernType.POSSIBLE_DUPLICATE_REQUIREMENT
        for concern in context.reconciliation.concerns
    ):
        rules.append(RequirementPolicyRule.POSSIBLE_DUPLICATE)
    return tuple(rules)


def _rule_requires_review(rule: RequirementPolicyRule) -> bool:
    return rule.value.startswith("RID-1") or rule.value.startswith("RID-4")


def _result(
    *,
    proposal_id: UUID,
    decision: PolicyDecision,
    rules: tuple[RequirementPolicyRule, ...],
    effects: tuple[RequirementTransitionEffect, ...] = (),
    new_results: tuple[NewRequirementPolicyResult, ...] = (),
    evidence_ids: tuple[UUID, ...] = (),
) -> RequirementPolicyResult:
    rules = _unique_rules(rules)
    return RequirementPolicyResult(
        proposal_id=proposal_id,
        policy_version=REQUIREMENT_POLICY_VERSION,
        decision=decision,
        requirement_effects=effects,
        new_requirement_results=new_results,
        triggered_rule_ids=rules,
        reasons=tuple(reason_for_requirement_policy_rule(rule) for rule in rules),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )


def _unique_rules(
    rules: tuple[RequirementPolicyRule, ...],
) -> tuple[RequirementPolicyRule, ...]:
    return tuple(dict.fromkeys(rules))
