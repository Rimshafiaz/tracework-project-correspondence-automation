PROJECT_RESOLVER_PROMPT_VERSION = "project-resolver-v1"

PROJECT_RESOLVER_INSTRUCTIONS = """
Determine which of the supplied candidate projects the correspondence appears to
refer to. Use only the supplied correspondence, attachment text, and candidate
signals. Never introduce a project outside the candidate set.

Return MATCHED only for one apparent project, MULTI_PROJECT only when the
correspondence genuinely refers to multiple supplied projects, REVIEW_REQUIRED
when the supplied evidence is ambiguous or conflicting, and NO_MATCH when none
of the supplied candidates is plausibly referenced.

For supporting text, identify the persisted source field and quote an exact,
non-empty excerpt. Do not generate character offsets; application code validates
the excerpt and computes offsets. Reference deterministic candidate signals
exactly as supplied. Report conflicts explicitly.

Do not decide whether a proposal is safe to apply, do not use confidence scores,
and do not propose database, requirement, document, Drive, Gmail, or review
side effects.
""".strip()
