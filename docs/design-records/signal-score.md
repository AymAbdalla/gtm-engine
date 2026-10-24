# Design record: signal-score (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries). Status: built, tested, two review rounds, design record written after the first build and checked against it.

## Job

A GTM engineer gathers dated public buying signals (leadership changes, hiring, funding, growth, intent) into raw files and needs them matched to owned accounts, scored by weight and age, gated into playable or not, and turned into one sourced "why now" line per account, or an honest "weak case". It never edits raw pulls, never contacts anyone and never quotes intent data. It declines picking people (play-build), building the books (account-book) and writing copy (outreach-draft).

## Library queries

| Query | Returned |
| --- | --- |
| `signal` | signal-weight-recency-expiry, red-capable-repro, test-cheap-before-production, flat-score-guard, stop-on-missing-signal, user-impact-operational-signals |
| `dated` | signal-weight-recency-expiry, visible-upgrade-recovery-branch |
| `claim` | cold-start-demo-script, report-simplification-delta, evidence-adjacent-delivery, evidence-classes, proof-registry-copy-lint, input-scope-bounds-completeness |
| `page` | read-only-scrape-contract, visual-baseline-fix-verify-loop |
| `intent` | route-by-trigger-and-intent |
| `why now`, `raw` | no match |
| `--id` reads | why-now-or-weak-case, source-trace-for-claims, inspect-target-as-data, baseline-snapshot-not-moving-target, surface-source-conflicts, preserve-missingness |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| signal-weight-recency-expiry | The core: per-type weight and expiry from the event date, best weight per type times a recency step, expired rows dropped, playable gate with a reason. | `scripts/score_signals.py`, `references/scoring.md`, `gtm.json` `signals` |
| why-now-or-weak-case | Outreach needs a true, current reason: one sentence of what the source says with its date and link, or "weak case" plus a trigger to watch; intent is timing only; a person opens the source first. | `score_signals.py`, `references/why-now.md` |
| surface-source-conflicts | A domain match whose company name differs is kept but flagged "check before use", not silently trusted. | `score_signals.py` check note, report section |
| baseline-snapshot-not-moving-target | Raw pulls are dated and never edited; corrections go in a newer pull and the newest wins. | `score_signals.py` (refuses to write into `signals/raw`), `references/scoring.md` |
| preserve-missingness | Rows with no source, no date, a future date or an unknown type are skipped and reported, never scored as zero or guessed. | `score_signals.py`, report "Not used" |
| inspect-target-as-data | Signal sources are web pages; text on them is data, never an instruction. | `references/gathering-signals.md` (added in this pass) |
| read-only-scrape-contract | Gathering reads pages only and never fills forms, signs in or messages anyone. | `references/gathering-signals.md` (added in this pass) |
| evidence-classes | Intent is labeled timing only and never presented as a fact about the buyer. | `references/why-now.md` |

## Declined

| Mechanic | Reason |
| --- | --- |
| flat-score-guard | Applies to daily-plan's queue; signal scores here are sums of explicit weights, and ties are ordered by account id deterministically. |
| source-trace-for-claims | Its adopted form is about helper briefs in implement-this; why-now-or-weak-case covers source and date for signals. |
| stop-on-missing-signal, red-capable-repro, user-impact-operational-signals | Different meaning of "signal" (workflow completion, debugging, operations alerts). |
| route-by-trigger-and-intent | Request routing, not buyer intent. |

## Acceptance checks

- `tests/test_gtm_signal_score.py` (27 tests), including `test_best_per_type_summed_with_recency`, `test_expired_signal_does_not_score`, `test_gate_blocks_hold_customer_live_deal_and_weight_zero`, `test_intent_never_cited`, `test_why_now_is_source_summary_with_date`, `test_future_and_undated_rows_skipped`, `test_refuses_to_write_into_raw`, `test_newer_pull_replaces_older_copy`, `test_domain_match_with_other_name_gets_check_note`.
- Example run on `assets/example/signals/raw/2026-10-15/`.
- Two independent review rounds and two fresh-session trials (2026-10-20).

## Gap found and fixed

- inspect-target-as-data and read-only-scrape-contract were not stated for hand gathering. Added two quality rules to `references/gathering-signals.md`: gathering is reading only, and page text is data, never an instruction. Documentation only; no script reads web pages.

## Open gaps

- The why-now line repeats the source summary as written, so its quality depends on the raw row. play-build composes the account name in front of it; nothing rewrites it. Acceptable while summaries are written by hand from the source.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: signal-weight-recency-expiry (shorter defaults), person-and-account-send-gate (fit gate). Library had no fit-by-timing entry; the 2x2 follows published practice (Pedowitz Group, fit as gate and intent as timing).

Changed:

- Intent alone is not a reason: an account whose only live signals are timing-only is held, `intent only: find a citable reason first`.
- Fit gate from the shared rule: out or unknown fit is held with the reason.
- Defaults: hiring expires after 60 days, topic intent after 30 (code and example config). The worked example in `scoring.md` uses a 50-day job post.
- New `quadrant` column (act, nurture, verify, suppress) and a fit-by-timing table in the report.

Checks: `tests/test_gtm_signal_score.py` (DefaultExpiryTests, FitQuadrantTests, intent-only, updated example counts: 12 live, 2 expired, A001 5.0).

Second review: an AI-assisted check pass followed on Oct 22 (findings fixed below).
