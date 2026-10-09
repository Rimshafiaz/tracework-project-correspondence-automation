# Held-out coverage plan

20 approved slots; EVAL-01 through EVAL-20 are authored, without model outputs. The newer
18–24-case scope supersedes the older implementation plan's approximately 30.
Difficulty mix: 6 easy, 8 medium, 6 hard. Categories below are coverage tags;
fixture category values will use the existing EvaluationCategory enum.

| ID | Primary coverage | Difficulty | Capability / scenario | Expected high-level outcome |
|---|---|---|---|---|
| EVAL-01 | Project resolution | Easy | One unique verified external project reference | Correct project; automatic project authorization |
| EVAL-02 | Project resolution | Medium | Project code embedded in a cost-allocation aside; trusted sender | Correct project; automatic project authorization |
| EVAL-03 | Project resolution | Easy | Unknown project with no plausible retrieved candidate | NO_MATCH; policy REVIEW_REQUIRED; no authoritative effects |
| EVAL-04 | Project resolution | Hard | Two distinct projects sharing the same displayed name; no phase identifier | REVIEW_REQUIRED; no guessed project link |
| EVAL-05 | Project resolution | Medium | Shared coordinator belongs to two projects; message omits project identity | REVIEW_REQUIRED; no guessed project link |
| EVAL-06 | Policy / authorization | Medium | Known-looking identifier exists only as unverified data; no other sufficient verified identifying signals | Unverified identifier excluded from retrieval; NO_MATCH; REVIEW_REQUIRED; no project link or authoritative mutation |
| EVAL-07 | Requirement reconciliation | Easy | A genuinely new, explicitly dated obligation | New-requirement proposal; REVIEW_REQUIRED; no requirement creation without approval |
| EVAL-08 | Requirement reconciliation | Easy | Completed subset with expressly outstanding scope | OPEN to PARTIAL under existing automatic policy |
| EVAL-09 | Policy / review | Medium | New delivery commitment changes an existing expected date without explicit correction language | REVIEW_REQUIRED; current date retained while pending |
| EVAL-10 | Policy / review | Easy | Explicit completion claim | Proposed SATISFIED; REVIEW_REQUIRED; current state retained while pending |
| EVAL-11 | Requirement reconciliation | Hard | Conditional or tentative sign-off, not established completion | REVIEW_REQUIRED; no automatic closure |
| EVAL-12 | Requirement reconciliation | Easy | Project-specific courtesy/logistics message unrelated to obligations | No requirement effect; no requirement mutation |
| EVAL-13 | Evidence / grounding | Medium | Progress conclusion needs two complementary filed notes; message supplies no substitute factual claim | Relevant existing evidence IDs selected; correct scoped PARTIAL update |
| EVAL-14 | Evidence / scope safety | Hard | Similarly named obligations and distracting evidence in another project | Only resolved-project evidence/effects; no other-project mutation |
| EVAL-15 | Evidence / validity | Medium | Withdrawn completion evidence is historical, with no valid replacement completion support | No invalidated evidence use or automatic closure; clarification/review |
| EVAL-16 | Correction | Medium | Explicit replacement date tied to identifiable prior supporting evidence | REVIEW_REQUIRED; explicit approval applies replacement date only |
| EVAL-17 | Correction | Hard | Completion claim explicitly corrected to incomplete remaining scope | REVIEW_REQUIRED; explicit approval applies supported state correction |
| EVAL-18 | Retraction | Medium | Entire obligation withdrawn; all valid supporting items explicitly accounted for | Explicit approval yields RETRACTED and targeted evidence invalidation, never deletion |
| EVAL-19 | Retraction / mutation safety | Hard | One supporting claim withdrawn while independent valid support remains | Explicit approval BLOCKED with REMAINING_SUPPORTING_EVIDENCE; no partial application/invalidation |
| EVAL-20 | Stale-content safety | Hard | An older quoted correction conflicts with current authoritative values and later valid support | Review/clarification; current values retained; no automatic overwrite |

First half: EVAL-01–10. Second half: EVAL-11–20.

## Label and safety rules

- Final source wording, identities, dates, and combinations must be new, not
  copied from unit tests, prompts, development fixtures, or live smoke data.
- Labels are fixed before any live model outputs are inspected. Authoring and
  validation use no live model calls. Leakage checks are completed before freeze.
- Optional exact evidence expectations are used only where the existing fixture
  IDs and facts make the required selection unambiguous. Do not fabricate IDs
  for newly persisted source excerpts or penalize equivalent valid grounding.
- Existing policy requires review for new requirements, dates, SATISFIED states,
  corrections, and retractions. OPEN to PARTIAL may auto-apply after all checks.
- Safety whitelists explicitly allow necessary project linkage while forbidding
  unintended requirement effects. A global no-authoritative-mutation flag is
  used only when project linkage must also remain absent.
- Approval is requested only for EVAL-16–19; the other cases do not implicitly
  apply pending reviews. Rejected/blocked application never means harness ERROR
  when it is represented by the existing observable domain outcome.

## Honest limits

EVAL-20 tests stale *content*, not a concurrent change after proposal creation.
The current static EvaluationCase has no mid-run mutation input. Likewise,
EVAL-14 tests cross-project exclusion/safety, not injection of an invalid model
proposal. Neither limitation will be disguised as runtime coverage or solved by
changing M22/production behavior in this milestone. Exact stale-review races and
malformed-proposal rejection remain covered by existing deterministic regressions.

The held-out manifest lists all twenty cases, frozen as version 1.0.0 for M24.

EVAL-16/17 require the observed invalidation of their corrected supporting item.
EVAL-18 requires both targeted invalidations using `required_actions`; merely
permitting those actions is insufficient. EVAL-19 instead forbids all partial
invalidation and expects the typed remaining-support block, not execution ERROR.
FollowUps cannot be seeded as active/historical fixtures by the current harness,
and its capture does not report cancellation state/reason. EVAL-18 therefore
does not claim live active-FollowUp cancellation coverage. EVAL-16 permits the
FollowUp row that normal lifecycle reconciliation can create after the date change.

EVAL-07 uses explicit runtime source-correspondence grounding rather than guessed
evidence IDs. Its requested date is in the source; the current result contract
does not expose a new proposal's date independently for scoring. Likewise,
EVAL-09/10 score review routing and retained authoritative date/state, not the
unexposed ordinary impact's proposed date/state. These are observation limits,
not claims of exact proposed-value coverage.
