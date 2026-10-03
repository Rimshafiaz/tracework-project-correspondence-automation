from app.contracts.requirement_policy import RequirementPolicyRule

REQUIREMENT_POLICY_VERSION = "requirement-policy/1"

_REASONS = {
    RequirementPolicyRule.PROPOSAL_TYPE_INVALID: "The proposal is not a requirement-reconciliation proposal.",
    RequirementPolicyRule.CONTEXT_SNAPSHOT_MISSING: "The M11 requirement context snapshot is missing or invalid.",
    RequirementPolicyRule.PROPOSAL_INTEGRITY_FAILED: "The persisted proposal does not match its typed M11 contract.",
    RequirementPolicyRule.PROJECT_LINK_INVALID: "The authoritative correspondence-project association is missing or inconsistent.",
    RequirementPolicyRule.REQUIREMENT_NOT_CURRENT: "A referenced requirement is missing or no longer belongs to the authoritative project.",
    RequirementPolicyRule.EVIDENCE_MISSING_OR_UNLINKED: "Required evidence is missing or is not linked to the M11 proposal.",
    RequirementPolicyRule.EVIDENCE_INVALIDATED: "Evidence required by the proposal is no longer valid.",
    RequirementPolicyRule.EVIDENCE_SCOPE_MISMATCH: "Supporting evidence is not scoped to the affected project and requirement.",
    RequirementPolicyRule.PROVENANCE_INTEGRITY_FAILED: "Persisted evidence provenance is missing or inconsistent.",
    RequirementPolicyRule.REQUIREMENT_STATE_STALE: "The requirement state changed after M11 evaluated it.",
    RequirementPolicyRule.EXPECTED_DATE_STALE: "The requirement expected date changed after M11 evaluated it.",
    RequirementPolicyRule.REQUIREMENT_DEFINITION_STALE: "The requirement definition changed after M11 evaluated it.",
    RequirementPolicyRule.REQUIREMENT_SET_STALE: "The project's requirement set changed after M11 evaluated it.",
    RequirementPolicyRule.SOURCE_CONTEXT_STALE: "The persisted correspondence, attachment, or evidence context changed after M11 evaluated it.",
    RequirementPolicyRule.NO_CHANGE: "M11 proposed no authoritative requirement change.",
    RequirementPolicyRule.OPEN_TO_PARTIAL: "M11 proposed OPEN to PARTIAL, which is the only low-risk state transition eligible for automatic authorization in this policy version.",
    RequirementPolicyRule.AUTO_ELIGIBLE: "All deterministic integrity, authority, freshness, evidence, provenance, concern, and conflict checks passed; policy did not independently reinterpret the correspondence semantics.",
    RequirementPolicyRule.SATISFIED_REQUIRES_REVIEW: "A proposed SATISFIED state requires human review in this policy version.",
    RequirementPolicyRule.BACKWARD_TRANSITION: "A backwards requirement-state transition requires human review.",
    RequirementPolicyRule.REVIEW_STATE_TRANSITION: "A transition into or out of REVIEW requires human review.",
    RequirementPolicyRule.EXPECTED_DATE_REQUIRES_REVIEW: "Expected-date mutations require human review in this policy version.",
    RequirementPolicyRule.M11_CONCERN: "M11 reported an unresolved semantic concern.",
    RequirementPolicyRule.M11_CONFLICT: "M11 reported conflicting evidence or interpretations.",
    RequirementPolicyRule.NEW_REQUIREMENT: "A proposed new authoritative requirement requires human review.",
    RequirementPolicyRule.POSSIBLE_DUPLICATE: "The new requirement may overlap an existing requirement and requires human review.",
    RequirementPolicyRule.INSUFFICIENT_SCOPED_EVIDENCE: "The proposed change lacks valid evidence scoped to the affected requirement.",
    RequirementPolicyRule.MULTI_IMPACT_ATOMIC_REVIEW: "At least one impact requires review, so the entire multi-impact proposal remains unapplied.",
}


def reason_for_requirement_policy_rule(rule: RequirementPolicyRule) -> str:
    return _REASONS[rule]
