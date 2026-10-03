from app.contracts.project_identity_policy import ProjectIdentityRule

PROJECT_IDENTITY_POLICY_VERSION = "project-identity/1"

PROJECT_IDENTITY_RULE_REASONS: dict[ProjectIdentityRule, str] = {
    ProjectIdentityRule.PROPOSAL_TYPE_INVALID: "The proposal is not a project-resolution proposal.",
    ProjectIdentityRule.CANDIDATE_SNAPSHOT_MISSING: "The candidate snapshot is missing or cannot be reconstructed.",
    ProjectIdentityRule.RESOLUTION_INTEGRITY_FAILED: "The proposed resolution is inconsistent with its supplied candidates or evidence.",
    ProjectIdentityRule.EVIDENCE_NOT_CURRENTLY_VALID: "Evidence required for authorization is no longer valid.",
    ProjectIdentityRule.PROVENANCE_UNVERIFIED: "The source record required to verify an identity signal could not be validated.",
    ProjectIdentityRule.NO_MATCH: "No plausible project was identified, so manual project assignment is required.",
    ProjectIdentityRule.RESOLVER_REVIEW_REQUIRED: "The resolver could not select a project without human review.",
    ProjectIdentityRule.RESOLVER_REPORTED_CONFLICT: "The resolver identified conflicting project evidence.",
    ProjectIdentityRule.APPROVED_CONVERSATION_LINK: "This conversation was previously approved for the proposed project.",
    ProjectIdentityRule.EXACT_PROJECT_CODE: "The correspondence contains an exact project-code match.",
    ProjectIdentityRule.EXACT_VERIFIED_IDENTIFIER: "The correspondence contains an exact verified project identifier.",
    ProjectIdentityRule.EXACT_DOCUMENT_IDENTIFIER: "An attached document contains an exact validated project identifier.",
    ProjectIdentityRule.KNOWN_PROJECT_CONTACT: "The sender is a known contact for the proposed project.",
    ProjectIdentityRule.KNOWN_CONTACT_ONLY: "A known contact without independent project identity is insufficient for automatic authorization.",
    ProjectIdentityRule.NORMALIZED_NAME_ONLY: "A normalized project-name match alone is insufficient for automatic authorization.",
    ProjectIdentityRule.ALIAS_ONLY: "A project alias alone is insufficient for automatic authorization.",
    ProjectIdentityRule.FUZZY_MATCH_ONLY: "A fuzzy project-name or alias match is insufficient for automatic authorization.",
    ProjectIdentityRule.SEMANTIC_INTERPRETATION_ONLY: "The semantic interpretation lacks an independent objective identity signal.",
    ProjectIdentityRule.UNKNOWN_OR_UNTRUSTED_SENDER: "The sender is not a known project contact and the conversation has no prior approved project link.",
    ProjectIdentityRule.INSUFFICIENT_INDEPENDENT_IDENTITY: "The available objective signals do not independently establish the proposed project.",
    ProjectIdentityRule.AUTO_APPROVED_CONVERSATION: "The approved conversation link permits automatic project resolution because no conflict was found.",
    ProjectIdentityRule.AUTO_PROJECT_CODE_AND_CONTACT: "An exact project code and known project contact permit automatic resolution because no conflict was found.",
    ProjectIdentityRule.AUTO_VERIFIED_IDENTIFIER_AND_CONTACT: "An exact verified identifier and known project contact permit automatic resolution because no conflict was found.",
    ProjectIdentityRule.SAME_TYPE_DIFFERENT_VALUES: "The same identifier type asserts incompatible values or projects.",
    ProjectIdentityRule.SAME_IDENTIFIER_MULTIPLE_PROJECTS: "The same verified identifier resolves to more than one project.",
    ProjectIdentityRule.BODY_ATTACHMENT_IDENTITY_CONFLICT: "The correspondence and attached document identify different projects.",
    ProjectIdentityRule.CONVERSATION_IDENTIFIER_CONFLICT: "The approved conversation project conflicts with a strong current identifier.",
    ProjectIdentityRule.MULTI_PROJECT_AUTO_ELIGIBLE: "Every separately supported project satisfies automatic authorization policy.",
    ProjectIdentityRule.MULTI_PROJECT_EVIDENCE_INCOMPLETE: "At least one proposed project lacks separately scoped evidence.",
    ProjectIdentityRule.MULTI_PROJECT_SCOPE_UNCLEAR: "The correspondence does not clearly separate the proposed projects.",
    ProjectIdentityRule.MULTI_PROJECT_PARTIAL_TRUST: "At least one proposed project does not independently satisfy automatic authorization policy.",
}


def reason_for_project_identity_rule(rule: ProjectIdentityRule) -> str:
    return PROJECT_IDENTITY_RULE_REASONS[rule]
