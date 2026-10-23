# Design record: crm-sync (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries).

## Job

Keep the book and a CRM in step through files. It compares `book/` and the log with a fresh CRM export, decides which side wins field by field, and writes change plans for both sides plus a review list. The caller applies the CRM plan by hand, pilot rows first. It never calls a CRM. It declines building the book (account-book), auditing CRM data quality as a one-off (data-quality audit mode), planning the day (daily-plan) and reporting results (funnel-review).

## Library queries

| Query | IDs returned |
| --- | --- |
| sync | explicit-audio-policy, file-based-two-way-sync |
| CRM | file-based-two-way-sync |
| export | faithful-export |
| conflict | authority-and-scope, parallelize-independent-slices, surface-source-conflicts |
| write | ambiguous-write-reconciliation, evidence-before-release-narrative, path-state-edit-fence, local-probe-can-have-side-effects, exact-write-preview |
| preview | preview-save-publish-separation, cheap-preview-gate, exact-write-preview |
| readback | exact-target-readback |
| vocabulary | glossary-code-crosscheck |
| idempotent | idempotent-state-with-atomic-replace |
| status | preserve-tool-result-contract, terminal-status |
| ambiguous | ambiguous-write-reconciliation |
| reconcil | bounded-repair-reconciliation, ambiguous-write-reconciliation |
| missing | preserve-missingness, test-observed-failure-before-fix, closed-roster-integrity, health-coverage-normalization, review-finding-truth-and-action, stop-on-invalid-input |
| match | scoped-finishing-chains, route-by-trigger-and-intent, two-layer-command-guard, strategy-ladder-first-match, guardrail-hook-pattern-match |
| dry | cleanup-dry-run-and-residuals |
| unknown | source-trace-for-claims, stop-when-structural-evidence-is-unknown |
| lock | calibrate-teaching-to-learner, terminal-status, guardrail-hook-pattern-match |
| newer, blank, row floor, pilot, rung, watermark, bounce, mapping, bulk, review queue | no match |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| file-based-two-way-sync | The skill's whole method: match ladder, newer change wins, every row accounted for, missing means closed or removed, row floors, plans to files. | `references/sync-rules.md`; `scripts/sync_crm.py` |
| preserve-missingness | A blank never overwrites, a future time counts as blank and becomes a conflict, unknown values go to review. | `references/sync-rules.md` |
| exact-write-preview | Write rungs (plan, copy, then a person applies live), a pilot batch, one named record per row, the field mapping shown. | `references/sync-rules.md`; `report.md` |
| exact-target-readback | Each CRM row shows the CRM's current value, the copy rung checks it, and confirmed changes drop off only when the next export shows them. | `references/sync-rules.md` |
| derive-state-from-append-only-log | Activity is turned into outcomes once, tracked by id; log rows are never edited in place. | "Activity is tracked by id" in `references/sync-rules.md` |
| ambiguous-write-reconciliation | Creates and logged activity are not safe to apply twice. A repeated create or log row now says when it was first planned and asks for a search before re-applying. | `planned_writes` in state; reason text; "Needs you" |
| idempotent-state-with-atomic-replace (write part) | The state holds the baseline every later run depends on; it is now written to a temp file and renamed into place. | `write_atomic` in `scripts/sync_crm.py`; `references/files.md` |
| bounded-repair-reconciliation | An outcome change not applied after `carry_forward_runs` plans moves to review instead of repeating forever. | `references/sync-rules.md` |
| surface-source-conflicts | When both sides changed and nothing says which is newer, the field goes to `conflicts.csv`; the script never picks. | `conflicts.csv` |
| person-and-account-send-gate (stop part) | A do-not-contact or opt-out on either side wins and reaches the book in the same run. | Outcomes table in `references/sync-rules.md` |

## Declined

| Mechanic | Reason |
| --- | --- |
| idempotent-state-with-atomic-replace (lock part) | One person runs the sync; a lock adds a stale-lock failure mode for no gain. Revisit if a scheduled run is added. |
| preview-save-publish-separation | Covered by the write rungs; there is no publish step. |
| glossary-code-crosscheck | The controlled vocabularies are config lists, not a glossary to cross-check against code. |
| faithful-export, cleanup-dry-run-and-residuals, stop-on-invalid-input, stop-when-structural-evidence-is-unknown | Different domains (visual exports, device cleanup, media input, code graphs). The row floor plays the stop-on-bad-input role here. |
| strategy-ladder-first-match, route-by-trigger-and-intent and other match-word hits | Not this job. |

## Conflicts resolved

- Rerun stability versus progress: a rerun on the same inputs reuses the starting state and does not save, so plans are identical; a new export moves the state on.
- Carry forward versus duplicates: field updates repeat safely until confirmed; creates and logged activity repeat with a "search first" warning.

## Gaps found and fixed in this pass

- Repeated create and log rows looked like new work and could be applied twice. They now carry their first planned date and a search-first note, and the report lists them. Test: `test_repeated_create_and_log_rows_ask_for_a_search_first`.
- `state.json` was written in place. It is now written whole or not at all. Test: `test_state_is_written_whole_or_not_at_all`. Example `expected/state.json` regenerated (new `planned_writes` key).

## Acceptance checks

`tests/test_gtm_crm_sync.py` (26 tests), including `test_blank_never_clears_a_value`, `test_both_changed_newer_time_wins_and_future_time_is_a_conflict`, `test_every_export_row_is_accounted_for`, `test_short_export_stops_and_keeps_state`, `test_crm_opt_out_becomes_do_not_contact_in_the_same_run_and_is_never_lost`, `test_same_inputs_give_the_same_plan_and_keep_the_state`, `test_live_rung_and_writing_into_inputs_are_refused` and `test_example_matches_expected`. `check_skill.py` on the skill folder.

## Open gaps

None found in this pass. Not tested: behavior in a fresh session after these edits.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: preserve-missingness (a blank never clears), surface-source-conflicts, staged-state-gates (mapping confirmation stated).

Changed:

- Optional `opportunities.csv`: an open opportunity plans `live_deal`; a book `live_deal` with no open opportunity plans `active`.
- Account `status`, `owner` and `relationship` from the CRM go to a new `sync/to-book-accounts.csv` for account-book's `input/account-updates.csv`.
- Ask, don't guess: without `--mapping-confirmed`, the report opens with "Mapping unconfirmed".
- The description says the script never writes to a CRM and a person applies the plan.

Checks: `tests/test_gtm_crm_sync.py` (AccountStatusTests, MappingConfirmationTests); `tests/test_gtm_shared.py` live-deal chain (fails if crm-sync's account updates are removed); expected files refreshed (fingerprint, new empty `to-book-accounts.csv`, report header).

An independent review followed on Oct 22.

Independent review (Oct 22) findings fixed: A book `live_deal` goes back to active only when the export has that account's opportunities and all are closed; one missing from the export stays live and the report names it. `opportunities.csv` now has the same row floor as people and accounts. Tests: AccountStatusTests.
