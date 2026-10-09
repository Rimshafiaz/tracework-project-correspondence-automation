import hashlib
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.ai.requirement_schemas import ExistingRequirementImpact, NewRequirementProposal, RequirementCorrectionKind, RequirementCorrectionProposal, RequirementEvidenceConflict, RequirementImpactDisposition, RequirementReconciliation, RequirementReconciliationConcern, RequirementReconciliationConcernType, RequirementSourceEvidence
from app.ai.schemas import ResolverSourceField
from app.contracts.requirement_policy import AuthoritativeProjectLinkRecord, RequirementCurrentEvidenceSnapshot, RequirementCurrentRecord, RequirementPolicyContext, RequirementPolicyEvidenceFact, RequirementPolicyRule
from app.contracts.requirement_reconciliation import RequirementContextSnapshot, RequirementEvidenceSnapshot, RequirementSnapshot
from app.models.enums import EvidenceValidity, PolicyDecision, ProposalType, RequirementState
from app.services.policy.requirement import evaluate_requirement_policy
from app.services.policy.requirement_persistence import build_requirement_policy_preview


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _context(
    *,
    observed_state: RequirementState = RequirementState.OPEN,
    current_state: RequirementState = RequirementState.OPEN,
    proposed_state: RequirementState | None = RequirementState.PARTIAL,
    observed_date: date | None = None,
    current_date: date | None = None,
    proposed_date: date | None = None,
    disposition: RequirementImpactDisposition = RequirementImpactDisposition.UPDATE_PROPOSED,
    evidence_validity: EvidenceValidity = EvidenceValidity.VALID,
    evidence_scoped: bool = True,
    link_valid: bool = True,
) -> RequirementPolicyContext:
    project_id = uuid4()
    event_id = uuid4()
    link_id = uuid4()
    requirement_id = uuid4()
    evidence_id = uuid4()
    body = "Neutral evidence records measurable progress."
    excerpt = "measurable progress"
    reference = RequirementSourceEvidence(
        correspondence_event_id=event_id,
        source_field=ResolverSourceField.BODY,
        excerpt=excerpt,
    )


    impact = ExistingRequirementImpact(
        requirement_id=requirement_id,
        disposition=disposition,
        proposed_state=proposed_state,
        proposed_expected_date=proposed_date,
        evidence=(reference,) if disposition is RequirementImpactDisposition.UPDATE_PROPOSED else (),
        interpretation="Neutral fixture interpretation.",
    )
    return RequirementPolicyContext(
        proposal_id=uuid4(),
        proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        correspondence_event_id=event_id,
        reconciliation=RequirementReconciliation(existing_impacts=(impact,)),
        m11_snapshot=RequirementContextSnapshot(
            project_id=project_id,
            authoritative_project_link_id=link_id,
            correspondence_event_id=event_id,
            body_sha256=_sha256(body),
            requirements=(
                RequirementSnapshot(
                    requirement_id=requirement_id,
                    name="Neutral requirement",
                    description="Neutral fixture obligation.",
                    current_state=observed_state,
                    expected_date=observed_date,
                ),
            ),
        ),
        authoritative_project_link=(
            AuthoritativeProjectLinkRecord(
                link_id=link_id,
                correspondence_event_id=event_id,
                project_id=project_id,
            )
            if link_valid
            else None
        ),
        current_requirements=(
            RequirementCurrentRecord(
                requirement_id=requirement_id,
                project_id=project_id,
                name="Neutral requirement",
                description="Neutral fixture obligation.",
                state=current_state,
                expected_date=current_date,
            ),
        ),
        current_body_sha256=_sha256(body),
        proposal_evidence=(
            RequirementPolicyEvidenceFact(
                evidence_item_id=evidence_id,
                correspondence_event_id=event_id,
                project_id=project_id,
                requirement_id=requirement_id if evidence_scoped else None,
                source_type="body",
                excerpt=excerpt,
                provenance_metadata={
                    "source_field": "BODY",
                    "start_offset": body.index(excerpt),
                    "end_offset": body.index(excerpt) + len(excerpt),
                },
                validity=evidence_validity,
            ),
        ) if disposition is RequirementImpactDisposition.UPDATE_PROPOSED else (),
    )


def _correction_context(kind: RequirementCorrectionKind = RequirementCorrectionKind.CORRECTION) -> RequirementPolicyContext:
    context = _context()
    requirement_id = context.m11_snapshot.requirements[0].requirement_id
    project_id = context.m11_snapshot.project_id
    prior_id = uuid4()
    prior_excerpt = "Earlier deadline was October 10"
    correction = RequirementCorrectionProposal(
        kind=kind,
        requirement_id=requirement_id,
        previous_state=RequirementState.OPEN,
        target_evidence_item_ids=(prior_id,),
        proposed_expected_date=date(2026, 10, 20) if kind is RequirementCorrectionKind.CORRECTION else None,
        evidence=(RequirementSourceEvidence(
            correspondence_event_id=context.correspondence_event_id,
            source_field=ResolverSourceField.BODY,
            excerpt="measurable progress",
        ),),
        interpretation="Later correspondence corrects earlier evidence.",
    )
    prior_snapshot = RequirementEvidenceSnapshot(
        evidence_item_id=prior_id,
        project_id=project_id,
        requirement_id=requirement_id,
        validity=EvidenceValidity.VALID,
        excerpt_sha256=_sha256(prior_excerpt),
    )
    prior_fact = RequirementPolicyEvidenceFact(
        evidence_item_id=prior_id,
        correspondence_event_id=uuid4(),
        project_id=project_id,
        requirement_id=requirement_id,
        source_type="body",
        excerpt=prior_excerpt,
        validity=EvidenceValidity.VALID,
    )
    return context.model_copy(update={
        "reconciliation": RequirementReconciliation(corrections=(correction,)),
        "m11_snapshot": context.m11_snapshot.model_copy(update={"existing_evidence": (prior_snapshot,)}),
        "current_snapshot_evidence": (RequirementCurrentEvidenceSnapshot(**prior_snapshot.model_dump()),),
        "proposal_evidence": (*context.proposal_evidence, prior_fact),
    })


def test_correction_and_retraction_require_review_without_auto_effect() -> None:
    for kind, rule in (
        (RequirementCorrectionKind.CORRECTION, RequirementPolicyRule.CORRECTION_REQUIRES_REVIEW),
        (RequirementCorrectionKind.RETRACTION, RequirementPolicyRule.RETRACTION_REQUIRES_REVIEW),
    ):
        context = _correction_context(kind)
        result = evaluate_requirement_policy(context)
        assert result.decision is PolicyDecision.REVIEW_REQUIRED
        assert rule in result.triggered_rule_ids
        assert result.requirement_effects == ()
        assert set(result.evidence_ids) == {item.evidence_item_id for item in context.proposal_evidence}


def test_correction_transition_preview_preserves_reviewed_target_and_values() -> None:
    context = _correction_context()
    result = evaluate_requirement_policy(context)
    evaluation = SimpleNamespace(
        id=uuid4(),
        policy_version=result.policy_version,
        decision=result.decision,
        triggered_rule_ids=[rule.value for rule in result.triggered_rule_ids],
        reasons=list(result.reasons),
    )

    preview = build_requirement_policy_preview(context=context, result=result, evaluation=evaluation)

    assert preview.disposition.value == "REVIEW"
    assert preview.proposed_state.values["correction_candidates"] == [
        context.reconciliation.corrections[0].model_dump(mode="json")
    ]


def test_ambiguous_correction_remains_review_required() -> None:
    context = _correction_context()
    context = context.model_copy(update={
        "reconciliation": context.reconciliation.model_copy(update={
            "concerns": (RequirementReconciliationConcern(
                concern_type=RequirementReconciliationConcernType.AMBIGUOUS_REQUIREMENT_MAPPING,
                candidate_requirement_ids=(context.m11_snapshot.requirements[0].requirement_id,),
                description="Prior statement may refer to another obligation.",
            ),),
        }),
    })
    result = evaluate_requirement_policy(context)
    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.M11_CONCERN in result.triggered_rule_ids


def test_stale_or_wrong_target_correction_is_rejected() -> None:
    context = _correction_context()
    changed = context.current_requirements[0].model_copy(update={"state": RequirementState.PARTIAL})
    stale = evaluate_requirement_policy(context.model_copy(update={"current_requirements": (changed,)}))
    assert stale.decision is PolicyDecision.REJECT_PROPOSAL
    assert RequirementPolicyRule.REQUIREMENT_STATE_STALE in stale.triggered_rule_ids

    prior = context.proposal_evidence[-1]
    wrong_target = evaluate_requirement_policy(context.model_copy(update={
        "proposal_evidence": (*context.proposal_evidence[:-1], prior.model_copy(update={"requirement_id": uuid4()})),
    }))
    assert wrong_target.decision is PolicyDecision.REJECT_PROPOSAL
    assert RequirementPolicyRule.EVIDENCE_SCOPE_MISMATCH in wrong_target.triggered_rule_ids

    invalid_target = evaluate_requirement_policy(context.model_copy(update={
        "proposal_evidence": (*context.proposal_evidence[:-1], prior.model_copy(update={"validity": EvidenceValidity.INVALIDATED})),
    }))
    assert invalid_target.decision is PolicyDecision.REJECT_PROPOSAL
    assert RequirementPolicyRule.EVIDENCE_INVALIDATED in invalid_target.triggered_rule_ids

    other_project = context.current_requirements[0].model_copy(update={"project_id": uuid4()})
    cross_project = evaluate_requirement_policy(context.model_copy(update={"current_requirements": (other_project,)}))
    assert cross_project.decision is PolicyDecision.REJECT_PROPOSAL
    assert RequirementPolicyRule.REQUIREMENT_NOT_CURRENT in cross_project.triggered_rule_ids


def test_open_to_partial_is_low_risk_trust_not_semantic_proof() -> None:
    result = evaluate_requirement_policy(_context())

    assert result.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert result.requirement_effects[0].triggered_rule_ids == (
        RequirementPolicyRule.OPEN_TO_PARTIAL,
        RequirementPolicyRule.AUTO_ELIGIBLE,
    )
    assert "did not independently reinterpret" in result.requirement_effects[0].reasons[1]


def test_satisfied_and_future_intent_completion_proposals_require_review() -> None:
    for current_state in (RequirementState.OPEN, RequirementState.PARTIAL):
        result = evaluate_requirement_policy(
            _context(
                observed_state=current_state,
                current_state=current_state,
                proposed_state=RequirementState.SATISFIED,
            )
        )

        assert result.decision is PolicyDecision.REVIEW_REQUIRED
        assert RequirementPolicyRule.SATISFIED_REQUIRES_REVIEW in result.triggered_rule_ids


def test_no_change_is_accepted_without_transition_effect() -> None:
    result = evaluate_requirement_policy(
        _context(
            proposed_state=None,
            disposition=RequirementImpactDisposition.NO_CHANGE,
        )
    )

    assert result.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert result.requirement_effects == ()
    assert result.triggered_rule_ids == (RequirementPolicyRule.NO_CHANGE,)


def test_expected_date_change_requires_review() -> None:
    proposed = date(2030, 5, 10)
    result = evaluate_requirement_policy(
        _context(proposed_state=None, proposed_date=proposed)
    )

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.EXPECTED_DATE_REQUIRES_REVIEW in result.triggered_rule_ids
    assert result.requirement_effects[0].proposed_expected_date == proposed


def test_invalidated_evidence_and_invalid_link_are_rejected() -> None:
    invalid_evidence = evaluate_requirement_policy(
        _context(evidence_validity=EvidenceValidity.INVALIDATED)
    )
    invalid_link = evaluate_requirement_policy(_context(link_valid=False))

    assert invalid_evidence.decision is PolicyDecision.REJECT_PROPOSAL
    assert invalid_evidence.triggered_rule_ids == (
        RequirementPolicyRule.EVIDENCE_INVALIDATED,
    )
    assert invalid_link.decision is PolicyDecision.REJECT_PROPOSAL
    assert invalid_link.triggered_rule_ids == (
        RequirementPolicyRule.PROJECT_LINK_INVALID,
    )


def test_stale_state_or_expected_date_requires_review_without_recalculation() -> None:
    stale_state = evaluate_requirement_policy(
        _context(current_state=RequirementState.PARTIAL)
    )
    stale_date = evaluate_requirement_policy(
        _context(current_date=date(2030, 1, 2))
    )

    assert stale_state.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.REQUIREMENT_STATE_STALE in stale_state.triggered_rule_ids
    assert stale_state.requirement_effects[0].observed_state is RequirementState.OPEN
    assert stale_state.requirement_effects[0].current_state is RequirementState.PARTIAL
    assert stale_date.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.EXPECTED_DATE_STALE in stale_date.triggered_rule_ids


def test_unscoped_evidence_and_review_state_transitions_require_review() -> None:
    unscoped = evaluate_requirement_policy(_context(evidence_scoped=False))
    review_state = evaluate_requirement_policy(
        _context(proposed_state=RequirementState.REVIEW)
    )

    assert unscoped.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.INSUFFICIENT_SCOPED_EVIDENCE in unscoped.triggered_rule_ids
    assert review_state.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.REVIEW_STATE_TRANSITION in review_state.triggered_rule_ids


def test_unknown_requirement_is_rejected_as_integrity_failure() -> None:
    context = _context()
    impact = context.reconciliation.existing_impacts[0].model_copy(
        update={"requirement_id": uuid4()}
    )
    context = context.model_copy(
        update={
            "reconciliation": RequirementReconciliation(
                existing_impacts=(impact,)
            )
        }
    )

    result = evaluate_requirement_policy(context)

    assert result.decision is PolicyDecision.REJECT_PROPOSAL
    assert result.triggered_rule_ids == (
        RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED,
    )


def test_m11_concern_and_conflict_require_review() -> None:
    context = _context()
    impact = context.reconciliation.existing_impacts[0]
    reference = impact.evidence[0]
    concern = RequirementReconciliationConcern(
        concern_type=RequirementReconciliationConcernType.INSUFFICIENT_EVIDENCE,
        candidate_requirement_ids=(impact.requirement_id,),
        evidence=(reference,),
        description="The supplied material is incomplete.",
    )
    conflict = RequirementEvidenceConflict(
        requirement_ids=(impact.requirement_id,),
        evidence=(reference, reference),
        description="The available statements conflict.",
    )
    context = context.model_copy(
        update={
            "reconciliation": context.reconciliation.model_copy(
                update={"concerns": (concern,), "conflicts": (conflict,)}
            )
        }
    )

    result = evaluate_requirement_policy(context)

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.M11_CONCERN in result.triggered_rule_ids
    assert RequirementPolicyRule.M11_CONFLICT in result.triggered_rule_ids


def test_new_requirement_and_possible_duplicate_require_review() -> None:
    context = _context()
    impact = context.reconciliation.existing_impacts[0]
    reference = impact.evidence[0]
    new_requirement = NewRequirementProposal(
        name="Neutral additional obligation",
        evidence=(reference,),
        interpretation="A new obligation may have been introduced.",
    )
    concern = RequirementReconciliationConcern(
        concern_type=RequirementReconciliationConcernType.POSSIBLE_DUPLICATE_REQUIREMENT,
        candidate_requirement_ids=(impact.requirement_id,),
        evidence=(reference,),
        description="The proposed obligation may already exist.",
    )
    context = context.model_copy(
        update={
            "reconciliation": context.reconciliation.model_copy(
                update={
                    "new_requirements": (new_requirement,),
                    "concerns": (concern,),
                }
            )
        }
    )

    result = evaluate_requirement_policy(context)

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert result.new_requirement_results[0].decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.NEW_REQUIREMENT in result.triggered_rule_ids
    assert RequirementPolicyRule.POSSIBLE_DUPLICATE in result.triggered_rule_ids
    assert RequirementPolicyRule.MULTI_IMPACT_ATOMIC_REVIEW in result.triggered_rule_ids


def test_multi_impact_policy_is_all_or_nothing() -> None:
    first = _context()
    second = _context()
    project_id = first.m11_snapshot.project_id
    event_id = first.correspondence_event_id
    link_id = first.m11_snapshot.authoritative_project_link_id
    second_snapshot = second.m11_snapshot.requirements[0]
    second_current = second.current_requirements[0].model_copy(
        update={"project_id": project_id}
    )
    second_reference = second.reconciliation.existing_impacts[0].evidence[0].model_copy(
        update={"correspondence_event_id": event_id}
    )
    second_impact = second.reconciliation.existing_impacts[0].model_copy(
        update={"evidence": (second_reference,)}
    )
    second_fact = second.proposal_evidence[0].model_copy(
        update={
            "correspondence_event_id": event_id,
            "project_id": project_id,
        }
    )
    context = first.model_copy(
        update={
            "reconciliation": RequirementReconciliation(
                existing_impacts=(
                    first.reconciliation.existing_impacts[0],
                    second_impact,
                )
            ),
            "m11_snapshot": first.m11_snapshot.model_copy(
                update={
                    "requirements": (
                        first.m11_snapshot.requirements[0],
                        second_snapshot,
                    )
                }
            ),
            "current_requirements": (
                first.current_requirements[0],
                second_current,
            ),
            "proposal_evidence": (
                first.proposal_evidence[0],
                second_fact,
            ),
            "authoritative_project_link": AuthoritativeProjectLinkRecord(
                link_id=link_id,
                correspondence_event_id=event_id,
                project_id=project_id,
            ),
        }
    )

    safe = evaluate_requirement_policy(context)
    assert safe.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert len(safe.requirement_effects) == 2

    unsafe_impact = second_impact.model_copy(
        update={"proposed_state": RequirementState.SATISFIED}
    )
    context = context.model_copy(
        update={
            "reconciliation": RequirementReconciliation(
                existing_impacts=(
                    first.reconciliation.existing_impacts[0],
                    unsafe_impact,
                )
            )
        }
    )
    mixed = evaluate_requirement_policy(context)

    assert mixed.decision is PolicyDecision.REVIEW_REQUIRED
    assert mixed.requirement_effects[0].decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert mixed.requirement_effects[1].decision is PolicyDecision.REVIEW_REQUIRED
    assert RequirementPolicyRule.MULTI_IMPACT_ATOMIC_REVIEW in mixed.triggered_rule_ids
