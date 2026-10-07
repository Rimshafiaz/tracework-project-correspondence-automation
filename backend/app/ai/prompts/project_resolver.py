PROJECT_RESOLVER_PROMPT_VERSION = "project-resolver-v2"

PROJECT_RESOLVER_INSTRUCTIONS = """
Determine which of the supplied candidate projects the correspondence appears to
refer to. Use only the supplied correspondence, attachment text, and candidate
signals. Never introduce a project outside the candidate set.

Return MATCHED only for one apparent project, MULTI_PROJECT only when the
correspondence genuinely refers to multiple supplied projects, REVIEW_REQUIRED
when the supplied evidence is ambiguous or conflicting, and NO_MATCH when none
of the supplied candidates is plausibly referenced.

Prefer the supplied typed candidate signal references for project identity
evidence. Reference deterministic candidate signals exactly as supplied.
Include source text evidence only when an exact quote is needed and you can
copy one contiguous substring verbatim from one named persisted source field:
SUBJECT, BODY, or one ATTACHMENT_TEXT field. Preserve every character,
punctuation mark, space, and line break exactly as supplied. Never paraphrase,
normalize whitespace or punctuation, or combine subject, body, or attachment
text into one excerpt. If an exact quote is unnecessary or cannot be copied
verbatim, omit the source excerpt rather than inventing or normalizing one.
Do not generate character offsets; application code validates any excerpt and
computes offsets. Report conflicts explicitly.

Do not decide whether a proposal is safe to apply, do not use confidence scores,
and do not propose database, requirement, document, Drive, Gmail, or review
side effects.
""".strip()
