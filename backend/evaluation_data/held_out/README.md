# Held-out evaluation dataset

Version 1.0.0 contains 20 independent cases: 6 easy, 8 medium, and 6 hard.
The slot-level difficulty and coverage matrix is in `COVERAGE.md`.

Coverage includes project resolution/authorization, requirement reconciliation,
policy and human-review routing, evidence grounding/scope/validity, corrections,
whole-requirement retractions, stale content, and mutation safety.

These are new fictional projects, contacts, correspondence, dates, and evidence
combinations, not copies of development fixtures, prompt examples, or known smoke
identities. Repository-local tests/prompts/development material is checked for
exact reuse. External live-smoke database records are not available to that check.
No live model output was used to author or tune the labels.

M24 is the first real live-model evaluation. Load the complete manifest with
`load_dataset(DatasetSplit.HELD_OUT)` and use `run_evaluation_cases` with an
explicit PostgreSQL evaluation engine. See `app/evaluation/README.md` for usage.
The runner uses isolated rollback-only schemas; never substitute production data
or invoke Gmail. Do not change labels or production behavior to make outputs pass.

Checks are deterministic: identity, review/policy outcome, current authoritative
state/date, selected evidence, correction targets/effects, and permitted,
forbidden, or required actions. EVAL-07 explicitly checks newly created source
grounding; EVAL-16–18 require targeted invalidation; EVAL-19 expects a domain
BLOCKED result, not execution ERROR. Test-model/synthetic compatibility checks
are not model evaluation scores.

Known observation limits:

- EVAL-20 tests stale content, not a post-proposal concurrency race. Exact stale
  review races remain covered by deterministic application regressions.
- EVAL-14 tests scope exclusion, not malformed-output injection.
- FollowUp cancellation is not independently scored or seeded as prior history.
- A new requirement's proposed date and ordinary proposed impact values are not
  separately exposed; EVAL-07/09/10 score the documented observable boundaries.
- No A/B provider comparison or subjective reply-quality scoring.

The manifest hash is SHA-256 of the filename-to-parsed-case mapping, serialized
as UTF-8 JSON with sorted keys, compact separators, and `ensure_ascii=False`.
Whitespace/line endings do not affect it. Tests verify manifest completeness
and the hash. Any later fixture edit requires an explicit dataset-version review.
