from uuid import UUID, uuid4

import pytest

from app.ai.schemas import CandidateSignalReference, EvidenceConflict, ProjectResolution, ResolutionConcern, ResolutionEvidence, ResolutionStatus, ResolverSourceField, SourceTextEvidence
from app.contracts.project_candidate import CandidateSignalSource, CandidateSignalType, ProjectCandidate, ProjectCandidateSet, ProjectCandidateSignal
from app.contracts.project_identity_policy import ProjectIdentityPolicyContext, ProjectIdentityRule
from app.models.enums import PolicyDecision, ProjectStatus, ProposalType
from app.services.policy import evaluate_project_identity, reject_missing_candidate_snapshot


def _signal(
    signal_type: CandidateSignalType,
    value: str,
    *,
    source: CandidateSignalSource = CandidateSignalSource.CORRESPONDENCE_EVENT,
    identifier_type: str | None = None,
    source_record_id: UUID | None = None,
    attachment_id: UUID | None = None,
    evidence_item_id: UUID | None = None,
) -> ProjectCandidateSignal:
    fuzzy = signal_type in {
        CandidateSignalType.FUZZY_NAME,
        CandidateSignalType.FUZZY_ALIAS,
    }
    return ProjectCandidateSignal(
        signal_type=signal_type,
        matched_value=value,
        source=source,
        identifier_type=identifier_type,
        source_record_id=source_record_id,
        attachment_id=attachment_id,
        evidence_item_id=evidence_item_id,
        exact=not fuzzy,
        verified=signal_type
        in {
            CandidateSignalType.VERIFIED_IDENTIFIER,
            CandidateSignalType.DOCUMENT_IDENTIFIER,
            CandidateSignalType.ALIAS,
            CandidateSignalType.FUZZY_ALIAS,
        },
        previously_approved=signal_type
        is CandidateSignalType.APPROVED_CONVERSATION,
        similarity_score=88.0 if fuzzy else None,
    )


def _candidate(*signals: ProjectCandidateSignal) -> ProjectCandidate:
    project_id = uuid4()
    return ProjectCandidate(
        project_id=project_id,
        project_code=f"CODE-{str(project_id)[:8]}",
        project_name=f"Project {str(project_id)[:8]}",
        project_status=ProjectStatus.ACTIVE,
        signals=signals,
    )


def _reference(candidate: ProjectCandidate, index: int = 0) -> CandidateSignalReference:
    signal = candidate.signals[index]
    return CandidateSignalReference(
        project_id=candidate.project_id,
        signal_type=signal.signal_type,
        matched_value=signal.matched_value,
        source=signal.source,
        identifier_type=signal.identifier_type,
        source_record_id=signal.source_record_id,
        attachment_id=signal.attachment_id,
        evidence_item_id=signal.evidence_item_id,
    )


def _resolution(
    status: ResolutionStatus,
    *candidates: ProjectCandidate,
    concerns: tuple[ResolutionConcern, ...] = (),
    conflicts: tuple[EvidenceConflict, ...] = (),
) -> ProjectResolution:
    if status is ResolutionStatus.NO_MATCH:
        return ProjectResolution(
            status=status,
            concerns=(ResolutionConcern.NO_PLAUSIBLE_CANDIDATE,),
        )
    return ProjectResolution(
        status=status,
        project_ids=tuple(candidate.project_id for candidate in candidates),
        evidence=tuple(
            ResolutionEvidence(
                project_id=candidate.project_id,
                signal_references=(_reference(candidate),),
                interpretation="The correspondence appears to concern this candidate.",
            )
            for candidate in candidates
        ),
        concerns=concerns,
        conflicts=conflicts,
    )


def _context(
    candidates: tuple[ProjectCandidate, ...],
    resolution: ProjectResolution,
    *,
    proposal_type: ProposalType = ProposalType.PROJECT_RESOLUTION,
    proposal_evidence_ids: tuple[UUID, ...] = (),
    invalidated_evidence_ids: tuple[UUID, ...] = (),
    validated_source_record_ids: tuple[UUID, ...] | None = None,
) -> ProjectIdentityPolicyContext:
    if validated_source_record_ids is None:
        validated_source_record_ids = tuple(
            signal.source_record_id
            for candidate in candidates
            for signal in candidate.signals
            if signal.source_record_id is not None
        )
    return ProjectIdentityPolicyContext(
        proposal_id=uuid4(),
        correspondence_event_id=uuid4(),
        proposal_type=proposal_type,
        resolution=resolution,
        candidate_set=ProjectCandidateSet(candidates=candidates),
        proposal_evidence_ids=proposal_evidence_ids,
        invalidated_evidence_ids=invalidated_evidence_ids,
        validated_source_record_ids=validated_source_record_ids,
    )


def _rules(result) -> set[ProjectIdentityRule]:
    return set(result.triggered_rule_ids)


def test_exact_project_code_and_known_contact_are_auto_eligible() -> None:
    contact_id = uuid4()
    candidate = _candidate(
        _signal(CandidateSignalType.PROJECT_CODE, "CODE-EXACT"),
        _signal(
            CandidateSignalType.PROJECT_CONTACT,
            "sender@example.test",
            source=CandidateSignalSource.PROJECT_RECORD,
            source_record_id=contact_id,
        ),
    )
    result = evaluate_project_identity(
        _context((candidate,), _resolution(ResolutionStatus.MATCHED, candidate))
    )

    assert result.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert ProjectIdentityRule.AUTO_PROJECT_CODE_AND_CONTACT in _rules(result)


def test_verified_identifier_and_known_contact_are_auto_eligible() -> None:
    identifier_id = uuid4()
    contact_id = uuid4()
    candidate = _candidate(
        _signal(
            CandidateSignalType.VERIFIED_IDENTIFIER,
            "external-123",
            identifier_type="external_reference",
            source_record_id=identifier_id,
        ),
        _signal(
            CandidateSignalType.PROJECT_CONTACT,
            "sender@example.test",
            source=CandidateSignalSource.PROJECT_RECORD,
            source_record_id=contact_id,
        ),
    )
    result = evaluate_project_identity(
        _context((candidate,), _resolution(ResolutionStatus.MATCHED, candidate))
    )

    assert result.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert ProjectIdentityRule.AUTO_VERIFIED_IDENTIFIER_AND_CONTACT in _rules(result)


def test_approved_conversation_without_conflict_is_auto_eligible() -> None:
    candidate = _candidate(
        _signal(
            CandidateSignalType.APPROVED_CONVERSATION,
            "conversation-1",
            source=CandidateSignalSource.APPROVED_CONVERSATION_LINK,
            source_record_id=uuid4(),
        )
    )
    result = evaluate_project_identity(
        _context((candidate,), _resolution(ResolutionStatus.MATCHED, candidate))
    )

    assert result.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert ProjectIdentityRule.AUTO_APPROVED_CONVERSATION in _rules(result)


@pytest.mark.parametrize(
    "signal, expected_rule",
    [
        (
            _signal(
                CandidateSignalType.PROJECT_CONTACT,
                "sender@example.test",
                source=CandidateSignalSource.PROJECT_RECORD,
                source_record_id=uuid4(),
            ),
            ProjectIdentityRule.KNOWN_CONTACT_ONLY,
        ),
        (
            _signal(CandidateSignalType.NORMALIZED_NAME, "example project"),
            ProjectIdentityRule.NORMALIZED_NAME_ONLY,
        ),
        (
            _signal(CandidateSignalType.ALIAS, "example", source_record_id=uuid4()),
            ProjectIdentityRule.ALIAS_ONLY,
        ),
        (
            _signal(CandidateSignalType.FUZZY_NAME, "example"),
            ProjectIdentityRule.FUZZY_MATCH_ONLY,
        ),
    ],
)
def test_insufficient_signals_require_review(
    signal: ProjectCandidateSignal,
    expected_rule: ProjectIdentityRule,
) -> None:
    candidate = _candidate(signal)
    result = evaluate_project_identity(
        _context((candidate,), _resolution(ResolutionStatus.MATCHED, candidate))
    )

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert expected_rule in _rules(result)
    assert ProjectIdentityRule.INSUFFICIENT_INDEPENDENT_IDENTITY in _rules(result)


def test_unknown_sender_with_exact_project_code_requires_review() -> None:
    candidate = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-EXACT"))
    result = evaluate_project_identity(
        _context((candidate,), _resolution(ResolutionStatus.MATCHED, candidate))
    )

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert ProjectIdentityRule.EXACT_PROJECT_CODE in _rules(result)
    assert ProjectIdentityRule.UNKNOWN_OR_UNTRUSTED_SENDER in _rules(result)


def test_no_match_and_resolver_abstention_require_review() -> None:
    no_match = evaluate_project_identity(
        _context((), _resolution(ResolutionStatus.NO_MATCH))
    )
    candidate = _candidate(_signal(CandidateSignalType.NORMALIZED_NAME, "example"))
    abstained = evaluate_project_identity(
        _context(
            (candidate,),
            _resolution(ResolutionStatus.REVIEW_REQUIRED, candidate),
        )
    )

    assert no_match.decision is PolicyDecision.REVIEW_REQUIRED
    assert _rules(no_match) == {ProjectIdentityRule.NO_MATCH}
    assert abstained.decision is PolicyDecision.REVIEW_REQUIRED
    assert ProjectIdentityRule.RESOLVER_REVIEW_REQUIRED in _rules(abstained)


def test_wrong_proposal_type_and_candidate_mismatch_are_rejected() -> None:
    candidate = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-1"))
    wrong_type = evaluate_project_identity(
        _context(
            (candidate,),
            _resolution(ResolutionStatus.MATCHED, candidate),
            proposal_type=ProposalType.REQUIREMENT_RECONCILIATION,
        )
    )
    other = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-2"))
    mismatch = evaluate_project_identity(
        _context((candidate,), _resolution(ResolutionStatus.MATCHED, other))
    )

    assert wrong_type.decision is PolicyDecision.REJECT_PROPOSAL
    assert _rules(wrong_type) == {ProjectIdentityRule.PROPOSAL_TYPE_INVALID}
    assert mismatch.decision is PolicyDecision.REJECT_PROPOSAL
    assert _rules(mismatch) == {ProjectIdentityRule.RESOLUTION_INTEGRITY_FAILED}


def test_invalidated_evidence_and_unverified_provenance_are_rejected() -> None:
    evidence_id = uuid4()
    candidate = _candidate(
        _signal(
            CandidateSignalType.PROJECT_CODE,
            "CODE-1",
            source=CandidateSignalSource.EVIDENCE_ITEM,
            evidence_item_id=evidence_id,
        )
    )
    invalidated = evaluate_project_identity(
        _context(
            (candidate,),
            _resolution(ResolutionStatus.MATCHED, candidate),
            proposal_evidence_ids=(evidence_id,),
            invalidated_evidence_ids=(evidence_id,),
        )
    )
    contact_id = uuid4()
    identifier_id = uuid4()
    unverified_candidate = _candidate(
        _signal(
            CandidateSignalType.VERIFIED_IDENTIFIER,
            "external-1",
            identifier_type="external_reference",
            source_record_id=identifier_id,
        ),
        _signal(
            CandidateSignalType.PROJECT_CONTACT,
            "sender@example.test",
            source=CandidateSignalSource.PROJECT_RECORD,
            source_record_id=contact_id,
        ),
    )
    unverified = evaluate_project_identity(
        _context(
            (unverified_candidate,),
            _resolution(ResolutionStatus.MATCHED, unverified_candidate),
            validated_source_record_ids=(),
        )
    )

    assert invalidated.decision is PolicyDecision.REJECT_PROPOSAL
    assert ProjectIdentityRule.EVIDENCE_NOT_CURRENTLY_VALID in _rules(invalidated)
    assert unverified.decision is PolicyDecision.REJECT_PROPOSAL
    assert ProjectIdentityRule.PROVENANCE_UNVERIFIED in _rules(unverified)


def test_missing_snapshot_has_a_pure_rejection_result() -> None:
    result = reject_missing_candidate_snapshot(
        proposal_id=uuid4(),
        resolver_status=ResolutionStatus.MATCHED,
    )

    assert result.decision is PolicyDecision.REJECT_PROPOSAL
    assert _rules(result) == {ProjectIdentityRule.CANDIDATE_SNAPSHOT_MISSING}


@pytest.mark.parametrize(
    "first_signal, second_signal, expected_rule",
    [
        (
            _signal(
                CandidateSignalType.VERIFIED_IDENTIFIER,
                "value-one",
                identifier_type="external_reference",
                source_record_id=uuid4(),
            ),
            _signal(
                CandidateSignalType.VERIFIED_IDENTIFIER,
                "value-two",
                identifier_type="external_reference",
                source_record_id=uuid4(),
            ),
            ProjectIdentityRule.SAME_TYPE_DIFFERENT_VALUES,
        ),
        (
            _signal(
                CandidateSignalType.VERIFIED_IDENTIFIER,
                "shared-value",
                identifier_type="external_reference",
                source_record_id=uuid4(),
            ),
            _signal(
                CandidateSignalType.VERIFIED_IDENTIFIER,
                "shared-value",
                identifier_type="external_reference",
                source_record_id=uuid4(),
            ),
            ProjectIdentityRule.SAME_IDENTIFIER_MULTIPLE_PROJECTS,
        ),
        (
            _signal(CandidateSignalType.PROJECT_CODE, "BODY-CODE"),
            _signal(
                CandidateSignalType.PROJECT_CODE,
                "DOCUMENT-CODE",
                source=CandidateSignalSource.ATTACHMENT,
                attachment_id=uuid4(),
            ),
            ProjectIdentityRule.BODY_ATTACHMENT_IDENTITY_CONFLICT,
        ),
        (
            _signal(
                CandidateSignalType.APPROVED_CONVERSATION,
                "conversation-1",
                source=CandidateSignalSource.APPROVED_CONVERSATION_LINK,
                source_record_id=uuid4(),
            ),
            _signal(CandidateSignalType.PROJECT_CODE, "OTHER-CODE"),
            ProjectIdentityRule.CONVERSATION_IDENTIFIER_CONFLICT,
        ),
    ],
)
def test_complete_candidate_snapshot_forces_deterministic_conflicts_to_review(
    first_signal: ProjectCandidateSignal,
    second_signal: ProjectCandidateSignal,
    expected_rule: ProjectIdentityRule,
) -> None:
    first = _candidate(first_signal)
    second = _candidate(second_signal)
    result = evaluate_project_identity(
        _context(
            (first, second),
            _resolution(ResolutionStatus.MATCHED, first),
        )
    )

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert expected_rule in _rules(result)


def test_resolver_reported_conflict_requires_review() -> None:
    candidate = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-1"))
    event_id = uuid4()
    first = SourceTextEvidence(
        correspondence_event_id=event_id,
        source_field=ResolverSourceField.BODY,
        excerpt="CODE-1",
    )
    second = SourceTextEvidence(
        correspondence_event_id=event_id,
        source_field=ResolverSourceField.SUBJECT,
        excerpt="Other reference",
    )
    conflict = EvidenceConflict(
        project_ids=(candidate.project_id,),
        source_evidence=(first, second),
        description="The supplied sources disagree.",
    )
    resolution = _resolution(
        ResolutionStatus.REVIEW_REQUIRED,
        candidate,
        concerns=(ResolutionConcern.CONFLICTING_EVIDENCE,),
        conflicts=(conflict,),
    )
    context = _context((candidate,), resolution)
    context = context.model_copy(update={"correspondence_event_id": event_id})

    result = evaluate_project_identity(context)

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert ProjectIdentityRule.RESOLVER_REPORTED_CONFLICT in _rules(result)


def test_genuine_multi_project_requires_every_project_to_pass() -> None:
    def strong_candidate(code: str) -> ProjectCandidate:
        return _candidate(
            _signal(CandidateSignalType.PROJECT_CODE, code),
            _signal(
                CandidateSignalType.PROJECT_CONTACT,
                "sender@example.test",
                source=CandidateSignalSource.PROJECT_RECORD,
                source_record_id=uuid4(),
            ),
        )

    first = strong_candidate("CODE-1")
    second = strong_candidate("CODE-2")
    allowed = evaluate_project_identity(
        _context(
            (first, second),
            _resolution(ResolutionStatus.MULTI_PROJECT, first, second),
        )
    )
    weak = _candidate(_signal(CandidateSignalType.NORMALIZED_NAME, "weak project"))
    partial = evaluate_project_identity(
        _context(
            (first, weak),
            _resolution(ResolutionStatus.MULTI_PROJECT, first, weak),
        )
    )

    assert allowed.decision is PolicyDecision.ALLOW_AUTO_ACTION
    assert ProjectIdentityRule.MULTI_PROJECT_AUTO_ELIGIBLE in _rules(allowed)
    assert partial.decision is PolicyDecision.REVIEW_REQUIRED
    assert ProjectIdentityRule.MULTI_PROJECT_PARTIAL_TRUST in _rules(partial)


def test_unclear_multi_project_scope_requires_review() -> None:
    first = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-1"))
    second = _candidate(_signal(CandidateSignalType.PROJECT_CODE, "CODE-2"))
    result = evaluate_project_identity(
        _context(
            (first, second),
            _resolution(
                ResolutionStatus.MULTI_PROJECT,
                first,
                second,
                concerns=(ResolutionConcern.MULTI_PROJECT_SCOPE_UNCLEAR,),
            ),
        )
    )

    assert result.decision is PolicyDecision.REVIEW_REQUIRED
    assert ProjectIdentityRule.MULTI_PROJECT_SCOPE_UNCLEAR in _rules(result)
