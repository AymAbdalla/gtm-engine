# Design record: data-quality (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries). Status: built, tested, two review rounds, design record written after the first build and checked against it.

## Job

A GTM engineer needs contact data that is safe and useful before anyone works it. Three modes: clean a people list into ready, later, review, enrich and quarantine files with a reason per person; split a list by a vendor verification file, failing closed; and audit a CRM export, score its health and write fix tickets that are rechecked before submission. Report-only: it never writes to a CRM. It declines defining the ICP (icp-define), building the books (account-book), scoring signals (signal-score) and writing messages (outreach-draft).

## Library queries

| Query | Returned |
| --- | --- |
| `contact` | contactability-triage, person-and-account-send-gate |
| `vendor` | channel-verdict-fail-closed |
| `verify` | visual-baseline-fix-verify-loop, size-work-as-checkable-units, verify-license-and-lineage |
| `duplicate` | explicit-prune-and-append, extend-owning-skill-before-new, bounded-repair-reconciliation, ambiguous-write-reconciliation |
| `audit` | two-tier-post-edit-and-stop-documentation, stage-audit-binary-analysis |
| `stale` | explicit-prune-and-append, plan-review-pipeline-with-eng-last, exact-target-readback, live-interface-schema-first |
| `coverage` | safety-critical-review-with-explicit-coverage-state, market-size-bands-with-noise, health-coverage-normalization |
| `health` | health-coverage-normalization |
| `report` | preview-save-publish-separation, proof-boundaries, rate-with-sample-and-interval, local-probe-can-have-side-effects, separate-report-and-repair-modes, report-simplification-delta |
| `fail` | snapshot-before-repair, safety-critical-review-with-explicit-coverage-state, preserve-prior-good-output, agent-run-failure-buckets, test-observed-failure-before-fix, fail-closed-review-parser |
| `cleanup` | cleanup-dry-run-and-residuals, conditional-cleanup |
| `write` | ambiguous-write-reconciliation, evidence-before-release-narrative, path-state-edit-fence, local-probe-can-have-side-effects, exact-write-preview |
| `match` | scoped-finishing-chains, route-by-trigger-and-intent, two-layer-command-guard, strategy-ladder-first-match, guardrail-hook-pattern-match |
| `dry run`, `ticket` (vertical-slice-ticket only), `quarantine` | no fitting match |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| contactability-triage | The core of clean mode: stop screens first, ordered persona ladder, phone types, defect flags, score, five files with reasons, never fuzzy matching. | `scripts/clean_list.py`, `references/clean-list.md` |
| channel-verdict-fail-closed | Verify mode must hold anyone a result does not clearly clear, per channel. | `scripts/verify_split.py`, `references/verify-split.md` |
| explainable-weighted-score | Both the contactability score and the health score drive decisions, so parts and weights must be visible and editable. | `gtm.json` `clean` and `audit.weights`; new `score_detail` column; audit table shows weight per check |
| health-coverage-normalization | A check that could not run (no sequences file) must not count as clean. Only checks that ran enter the score; not-run checks are listed. | `scripts/audit_crm.py` `health()`, report "Not run" line |
| evidence-adjacent-delivery | Audit report leads with scope and limits, says "no blockers found within scope", and gives Evidence, Fix and Verify per finding. | `scripts/audit_crm.py` report, `references/audit-crm.md` |
| exact-target-readback | A ticket is submitted only if the export still holds the recorded current value; recheck splits ready, skip and drift. | `audit_crm.py recheck`, `references/fix-tickets.md` |
| separate-report-and-repair-modes | The skill only reports and writes files; every fix is the user's action. | SKILL.md ground rules |
| cleanup-dry-run-and-residuals | Planned changes are listed for approval (`fixes.csv`) and never applied by the skill. | `references/fix-tickets.md` |
| preserve-missingness | A blank last touch means never touched; "vendor has no record" is not proof someone left. | `clean_list.py`, `references/clean-list.md` |

## Declined

| Mechanic | Reason |
| --- | --- |
| person-and-account-send-gate | The email gate belongs to account-book; data-quality says "ready means usable, not cleared to email". |
| safety-critical-review-with-explicit-coverage-state | Built for code review with outside reviewers; the idea it shares (show what did not run) is covered by health-coverage-normalization. |
| ambiguous-write-reconciliation, bounded-repair-reconciliation | About uncertain writes to outside systems; this skill never writes to one. |
| explicit-prune-and-append | Personal learning logs, not contact records. |
| strategy-ladder-first-match | account-book's job. |
| snapshot-before-repair, preserve-prior-good-output, conditional-cleanup | Inputs are never changed, so there is nothing to snapshot or restore. |

## Acceptance checks

- `tests/test_gtm_data_quality.py` (40 tests), including `test_do_not_contact_wins`, `test_do_not_contact_beats_a_duplicate_row`, `test_not_buyer_beats_persona`, `test_fail_closed_cases`, `test_email_result_never_clears_a_call`, `test_health_formula`, `test_sequence_check_not_run_without_file`, `test_recheck_splits_ready_skip_drift`, `test_report_leads_with_scope_and_never_says_pass`, and the new `test_score_detail_adds_up`.
- Example runs of all three scripts on `assets/example/`.
- Two independent review rounds and two fresh-session trials (2026-10-20).

## Gap found and fixed

- explainable-weighted-score: the contactability score had no visible breakdown. Added `score_detail` (each part with its sign) to the clean outputs, documented in `references/clean-list.md`, tested by `test_score_detail_adds_up` (the parts sum to the score).

## Open gaps

- None found against the selected mechanics.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: preserve-missingness, person-and-account-send-gate (one ICP rule shared with the book).

Changed:

- ICP screen uses the shared fit rule: out is quarantined, unknown fit goes to `enrich.csv`. The audit tickets only known out-of-ICP accounts.
- LinkedIn links that carry an id (Sales Navigator lead links, `/in/ACwAA...`) skip the profile-name check.
- Two people at one account with the same phone and last name go to review.
- Step 3 proposes a `gtm.json` change and waits for a yes. The description no longer offers account deduping.

Checks: `tests/test_gtm_shared.py`; `tests/test_gtm_data_quality.py` MatchingProbeTests; two account-screen assertions now use the shared reason wording.

An independent review followed on Oct 22.

Independent review (Oct 22) findings fixed: LinkedIn member ids are matched case-sensitively (`ACoAA...`, `ACwAA...`), so a name slug like `acosta-maria` still gets the name check. Test: MatchingProbeTests.
