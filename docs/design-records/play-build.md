# Design record: play-build (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries).

## Job

Design and fill one outbound play from the account book: who qualifies, who at each account gets the touch, how many start each day, and when the play stops. The caller is a GTM engineer or SDR who wants a proposed enrollment list they can approve row by row. It writes `plays/<play_id>/` files only. It declines list cleaning (data-quality), book building (account-book), signal scoring (signal-score), copywriting (outreach-draft) and today's touch list (daily-plan), and it never enrolls anyone in a real tool.

## Library queries

| Query | IDs returned |
| --- | --- |
| eligibility funnel campaign | counted-eligibility-funnel |
| campaign | counted-eligibility-funnel |
| outreach | why-now-or-weak-case, derive-state-from-append-only-log, person-and-account-send-gate |
| reactivation quiet accounts | reactivation-by-own-rhythm |
| override reasons rule | override-reasons-become-rules |
| append-only log state | derive-state-from-append-only-log |
| send gate person account | person-and-account-send-gate |
| rebuild | rebuild-keeps-user-edits, shared-context-artifact |
| signal | signal-weight-recency-expiry, red-capable-repro, test-cheap-before-production, flat-score-guard, stop-on-missing-signal, user-impact-operational-signals |
| owner | stage-card-readiness-and-ownership, stage-ownership |
| one live | strategy-ladder-first-match, promise-payoff-honesty |
| sequence | sequence-date-math-with-shift, escalate-proof-by-ambiguity |
| progress | decision-map-with-fog, three-strike-hypothesis-loop, milestone-progress-communication |
| stall | installed-toolkit-review, visible-upgrade-recovery-branch, least-scope-connection-discovery |
| duplicate | explicit-prune-and-append, extend-owning-skill-before-new, bounded-repair-reconciliation, ambiguous-write-reconciliation |
| approval / approve | plan-review-pipeline-with-eng-last, evidence-ledger-with-individual-remedy-approval, phase-gated-discovery-to-approved-spec |
| user edits | stop-at-user-owned-render-gate |
| seat, round-robin, cadence, why now, enroll, drop reasons count | no match |
| cap, consent | capability and browser-consent entries only (not this job) |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| counted-eligibility-funnel | The play's core promise: nobody leaves without a counted reason, and the counts must add up. | `scripts/build_play.py` Funnel and `write_funnel`; `references/eligibility.md`; `funnel.md` now states the add-up check |
| person-and-account-send-gate | The book's gate already blocks people for who they are and where they work; the play must not reopen that. | Rule 6 in `references/eligibility.md`; reads `send_ok`, `call_ok` |
| strategy-ladder-first-match | Excluded, hold and live-deal accounts stay out by the book's strategy. | Rule 2 in `references/eligibility.md` |
| why-now-or-weak-case | A first touch may quote only a confirmed, dated fact, and a person opens the source first. | `trigger_fact` rules in `references/play-types.md`; "Needs you" in `report.md` |
| reactivation-by-own-rhythm | Win-back plays judge quiet by each account's own gap and apply the recent-touch rule. | Reactivation in `references/play-types.md`; rule 8 |
| override-reasons-become-rules | Manual adds and removals need reasons, and repeats become rule ideas; another owner's account is a counted drop. | `overrides.csv`, rule 3, rule ideas in `report.md` |
| derive-state-from-append-only-log | Stop outcomes, open conversations and recent touches come from the log, not stored fields. | Rules 4, 4b and 8 |
| rebuild-keeps-user-edits | Reruns keep what the user typed (`approved`, filled variables) and the seats of approved rows. | "Rows that change" in `references/eligibility.md` |
| human-ticked-draft-file (variant) | The person approves each row; the script never enrolls. | `approved` column; SKILL.md steps 4 and 6 |
| sequence-date-math-with-shift (start dates only) | Start dates skip weekends and holidays; the shift itself belongs to daily-plan. | "Start dates" in `references/eligibility.md` |
| bounded-loop (stop condition) | A play that finds nobody new for `max_quiet_runs` runs says to retire it. | `state.json` runs, report line |

## Declined

| Mechanic | Reason |
| --- | --- |
| signal-weight-recency-expiry, flat-score-guard | Owned by signal-score and daily-plan; play-build only reads their outputs. |
| explainable-weighted-score | Ranking reuses signal-score's explained score and the account tier; no new composite is built here. |
| explicit-prune-and-append, decision-map-with-fog, phase-gated-discovery-to-approved-spec | Different jobs (learning notes, planning tickets, spec interviews). |
| ambiguous-write-reconciliation, bounded-repair-reconciliation | No external writes happen here. |
| stage-card-readiness-and-ownership, stage-ownership | Process design belongs to motion-map. |
| stop-at-user-owned-render-gate, promise-payoff-honesty, escalate-proof-by-ambiguity, capability and consent entries | Unrelated domains returned by single-word matches. |

## Conflicts resolved

- One live play per person versus a new strong signal: the person stays in the running play and is listed under "reply in that thread instead". The play never stacks two sequences.
- Keeping approvals versus safety: an approved row that a rule now blocks keeps `approved=yes` with a `drop_reason` so the user sees it, and daily-plan never works a row with a `drop_reason`. A row that qualifies again needs a fresh approval.

## Gaps found and fixed in this pass

- The funnel did not state its own add-up check. `write_funnel` now writes "start minus removed equals proposed" or a loud FAILED line. Tests: `test_every_drop_counted_and_funnel_adds_up`, `test_funnel_check_flags_counts_that_do_not_add_up`.
- The report did not tell the user to open each source before the first touch when a row quotes a dated fact. It now lists those rows under "Needs you". Test: `test_trigger_fact_reads_after_i_saw`.
- Example outputs regenerated (`plays/signal-oct/funnel.md`, `report.md`; `plays/winback-q4/funnel.md`).

## Acceptance checks

`tests/test_gtm_play_build.py` (39 tests), including `test_every_drop_counted_and_funnel_adds_up`, `test_unconfirmed_fact_is_never_quoted`, `test_missing_named_leader_falls_back_and_is_reported`, `test_reactivation_skips_people_touched_recently_even_when_tagged`, `test_rerun_keeps_typed_variables`, `test_blocked_flag_stays_until_you_clear_approved`, `test_repeated_reason_becomes_a_rule_idea`, `test_stalled_play_is_reported`, `test_inputs_unchanged_and_only_play_folder_written` and `test_example_reproduces_committed_outputs`. `check_skill.py` on the skill folder.

## Open gaps

None found in this pass. Not tested: behavior in a fresh session after these edits.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: staged-state-gates (stop on missing settings), skill-evaluation-needs-calibrated-holdouts (holdout idea, applied to plays), strategy-ladder-first-match (status checked again).

Changed:

- Ask, don't guess: the script refuses a play.json without `channel`, `start`, `daily_cap` or `sequence` and writes nothing; step 1 says ask and stop.
- Rule 2 also checks the account's own status (`live_deal`, `hold`, `archived`) whatever the strategy.
- Optional `holdout_share` (0 to 0.5): a stable hash of play id and account id holds accounts out, counted in the funnel.
- SKILL.md documents the 10-day default sequence length when `sequences.json` is missing.

Checks: `tests/test_gtm_play_build.py` (MissingSettingsTests, HoldoutTests, LiveDealTests); test helper now sets `daily_cap`; example outputs regenerated (one reason now says `account status live_deal`).

Second review: an AI-assisted check pass followed on Oct 22 (findings fixed below).

Second review (Oct 22) findings fixed: The holdout now runs after seat choice, so it counts the seat that would have been touched (the same unit as the worked side), and an override cannot add someone back at a held-out account. Tests: HoldoutTests.
