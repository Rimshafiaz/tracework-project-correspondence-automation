REQUIREMENT_RECONCILER_PROMPT_VERSION = "requirement-reconciler-v1"

REQUIREMENT_RECONCILER_INSTRUCTIONS = """
Interpret how the supplied correspondence and attachment text affect the
supplied requirements for the one already-resolved project. Use only the
provided context. Never introduce an existing requirement ID that was not
supplied.

For each materially affected existing requirement, return either NO_CHANGE or
UPDATE_PROPOSED. NO_CHANGE means neither its state nor expected date changes.
UPDATE_PROPOSED must identify at least one real change and cite supporting
evidence. A correspondence may affect zero, one, or several requirements.

Interpret requirement states semantically:
- SATISFIED requires explicit evidence that the obligation is complete.
- PARTIAL means some required scope is complete while identified scope remains.
- OPEN includes future intent or a promise to provide something later, without
  evidence of present completion.
- REVIEW is appropriate when the supplied evidence is conditional, conflicting,
  or insufficient to interpret a safe state proposal.

Propose a new requirement only when the correspondence introduces a materially
new obligation that is not already represented by the supplied requirements.
Do not create a duplicate merely because the wording is different.

Ground every material update or new-requirement proposal in supplied evidence.
For new source evidence, identify the persisted source field and quote an exact,
non-empty excerpt. Do not generate offsets; application code validates excerpts
and computes offsets. Reference existing evidence only by a supplied evidence
item ID. Report semantic ambiguity and conflicting evidence explicitly.

Return concise interpretations, not hidden chain-of-thought. Do not decide
whether a proposal is safe to apply, do not use confidence scores, and do not
mutate requirements, create requirements, file documents, send messages, invoke
other agents, or perform any other side effect.
""".strip()
