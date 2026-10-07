from app.contracts.document_revision import DocumentRevisionRule


_REASONS = {
    DocumentRevisionRule.SUPPORTED_NUMERIC_REVISION: (
        "The filename ends with a supported numeric revision label."
    ),
    DocumentRevisionRule.FIRST_REVISION_CURRENT: (
        "No existing document is current for this clean document family."
    ),
    DocumentRevisionRule.NEWER_REVISION_CURRENT: (
        "The incoming numeric revision is newer than the current revision."
    ),
    DocumentRevisionRule.OLDER_REVISION_HISTORICAL: (
        "The incoming numeric revision is older than the current revision."
    ),
    DocumentRevisionRule.SAME_REVISION_SAME_CONTENT_DUPLICATE: (
        "The same revision and content were already retained for this family."
    ),
    DocumentRevisionRule.SAME_REVISION_DIFFERENT_CONTENT_REVIEW: (
        "The same revision label exists with different content."
    ),
    DocumentRevisionRule.UNSUPPORTED_REVISION_REVIEW: (
        "The filename contains a revision label that this policy cannot order."
    ),
    DocumentRevisionRule.MISSING_REVISION_REVIEW: (
        "The filename does not contain a supported terminal revision label."
    ),
    DocumentRevisionRule.FAMILY_UNASSESSED_REVIEW: (
        "The document family contains unresolved or inconsistent revision history."
    ),
}


def reason_for_document_revision_rule(rule: DocumentRevisionRule) -> str:
    return _REASONS[rule]
