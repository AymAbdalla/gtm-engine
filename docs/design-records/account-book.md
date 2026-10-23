# Design record: account-book (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries). Status: built, tested, three review rounds, design record written after the first build and checked against it.

## Job

A GTM engineer needs one working record per person (the prospect book) and per account (the account book) that can be rebuilt from sources without losing hand edits, with a gate that says who may be emailed, called or messaged and why not, one strategy per account, buying-group coverage, a CRM fixes list and a stable top-accounts list. Files only. It declines cleaning lists (data-quality), scoring signals (signal-score), filling plays (play-build) and syncing with the CRM (crm-sync).

## Library queries

| Query | Returned |
| --- | --- |
| `rebuild` | rebuild-keeps-user-edits, shared-context-artifact |
| `edit` | two-tier-post-edit-and-stop-documentation, path-state-edit-fence, parallelize-independent-slices, editorial-rules-need-calibration, explicit-edit-maps, rebuild-keeps-user-edits |
| `send` | channel-verdict-fail-closed, human-ticked-draft-file, person-and-account-send-gate |
| `strategy` | strategy-ladder-first-match |
| `focus list`, `stable` | sticky-top-list-with-challengers (plus baseline-snapshot-not-moving-target, stable-state-identities, stable-task-outcome-evaluation for `stable`) |
| `top` | red-capable-repro, bounded-design-review-and-context-modes, override-reasons-become-rules, machine-checkable-quality-bar, rate-with-sample-and-interval, summary-keeps-severity |
| `conflict` | authority-and-scope, parallelize-independent-slices, surface-source-conflicts |
| `buying` | signal-weight-recency-expiry, reactivation-by-own-rhythm |
| `gate` | staged-state-gates, health-coverage-normalization, review-receipt-and-delta-rereview, investigate-cause-before-fix, phase-gated-discovery-to-approved-spec, cheap-preview-gate |
| `committee`, `lane`, `time zone`, `merge` | no match |
| `export` | faithful-export |
| `--id` reads | explainable-weighted-score, stage-ownership, preserve-missingness |

Buying-group lanes and roles, the "pain stays a hypothesis" rule and area-code time zones have no library entry; they come from the author's own outbound method.

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| rebuild-keeps-user-edits | The book is edited by hand and rebuilt from sources; edits must survive every rebuild. `.built/` stores last source values, not the last book (the entry's counterexample). | `scripts/build_book.py`, `references/merge-rules.md` |
| person-and-account-send-gate | Email quality alone lets competitors and non-buyers through. One gate per channel combines person and account reasons, each recorded; exports list who was left out. | `build_book.py` send, follow-up, call and LinkedIn gates; `references/send-gate.md` |
| strategy-ladder-first-match | Every account gets exactly one next play with a reason; a manual override sticks. | `build_book.py` strategy ladder; `references/strategy.md` |
| sticky-top-list-with-challengers | A focus list must stay stable to be worked, while better candidates are still reported. | `scripts/rank_accounts.py` |
| explainable-weighted-score | Top-list points show a one-line reason for each part; weights live in `gtm.json` `ranking`. | `rank_accounts.py` `points()` |
| surface-source-conflicts | Ambiguous names and source-side status changes are logged to `conflicts.csv`, not silently resolved. | `build_book.py`, `references/merge-rules.md` |
| preserve-missingness | A blank source value never erases a known one; an approximate time zone is labeled as such. | `build_book.py`, tests below |

## Declined

| Mechanic | Reason |
| --- | --- |
| channel-verdict-fail-closed | data-quality's verify mode does this; the book reads its result as `input/verified.csv`. |
| override-reasons-become-rules | play-build's job; the book keeps overrides but does not mine them. |
| authority-and-scope | The book's source precedence (`book.sources`) already settles which source wins; no extra mechanism needed. |
| faithful-export, stage-ownership, staged-state-gates, others above | Wrong job (visual export, process roles, build stages). |

## Acceptance checks

- `tests/test_gtm_account_book.py` (25 tests), including `test_edits_survive_three_rebuilds`, `test_blank_source_then_new_value_updates_the_book`, `test_gate_blocks_accounts_and_people_we_must_not_email`, `test_linkedin_gate_blocks_the_same_people_and_needs_a_profile`, `test_any_reply_at_the_account_stops_followups`, `test_ladder_first_match_wins`, `test_sticky_list_reports_challengers`, `test_live_deals_and_user_relationships_are_never_ranked`, `test_example_rebuild_matches_its_readme`.
- Three independent review rounds and two fresh-session trials (2026-10-20).

## Gaps

- None found against the selected mechanics in this pass.
- Not built (original method, no library entry): verifying buying-group contacts riskiest first, capped per account. Proposal: an optional `verify_order` column in the book ranking contacts by staleness and defects, if wanted.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: strategy-ladder-first-match (reordered), person-and-account-send-gate (fit added), preserve-missingness.

Changed:

- Strategy ladder: live is rule 3, above re-engage. An account with an open deal is never contacted, even after a past reply. The old test expecting re-engage was changed to live (requirement change).
- Gate: out-of-ICP accounts are held (`outside the ICP: ...`); unknown fit blocks every channel with `fit unknown: enrich first`.
- `input/account-updates.csv` (from crm-sync) overlays status, owner and relationship as source values; an open deal sets `live_deal` even over a hand edit.
- Ready also needs the roles in `book.ready_requires_roles` (default decision maker).
- Ranking adds ICP fit points (`ranking.fit_points`, default sweet spot 5, segment match 2, in band 0) so a great fit beats a well-staffed poor fit.

Checks: `tests/test_gtm_account_book.py` (live-deal probe, AccountUpdateTests, FitRankingAndReadinessTests); `tests/test_gtm_shared.py` probe and live-deal chain.

An independent review followed on Oct 22.

Independent review (Oct 22) findings fixed: A manual `strategy_override` no longer beats the blocking rules (parent decides, excluded, hold, outside the ICP, archived, live deal); the reason says the override was not applied. `status` is compared without case. Test: StrategyTests.
