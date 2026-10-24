# Design record: daily-plan (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries).

## Job

Turn approved enrollments, sequence templates and the activity log into today's work file, place calls in the prospect's legal hours, and close the day so every planned card is accounted for. The caller works touches by hand. It writes `plan/` files only. It declines building plays (play-build), writing copy (outreach-draft), syncing with a CRM (crm-sync) and reporting results (funnel-review), and it never sends, dials or enrolls.

## Library queries

| Query | IDs returned |
| --- | --- |
| sequence | sequence-date-math-with-shift, escalate-proof-by-ambiguity |
| business day | sequence-date-math-with-shift |
| missed | sequence-date-math-with-shift, learner-knowledge-ledger |
| priority | flat-score-guard |
| day close | zero-unaccounted-day-close |
| weighted | explainable-weighted-score |
| score | gather-first-score-later, flat-score-guard, multidimensional-risk, explainable-weighted-score |
| log | explicit-prune-and-append, least-scope-connection-discovery, procedure-over-session-log, derive-state-from-append-only-log |
| state | state-machine-for-resumable-engine-setup, idempotent-state-with-atomic-replace, derive-state-from-append-only-log, motion-uses-feedback-and-interruption, preview-save-publish-separation, plan-review-pipeline-with-eng-last |
| account | zero-unaccounted-day-close, person-and-account-send-gate, signal-weight-recency-expiry, strategy-ladder-first-match, reactivation-by-own-rhythm, identity-not-import-receipt |
| missing | preserve-missingness, test-observed-failure-before-fix, closed-roster-integrity, health-coverage-normalization, review-finding-truth-and-action, stop-on-invalid-input |
| stale | explicit-prune-and-append, plan-review-pipeline-with-eng-last, exact-target-readback, live-interface-schema-first |
| user's | gather-first-score-later, delivered-surface-visual-review, stop-at-user-owned-render-gate, milestone-progress-communication, exact-write-preview, path-state-edit-fence |
| preserve | faithful-export, platform-specific-adaptation, explicit-edit-maps, stable-state-identities, editable-evidence-lineage, conditional-cleanup |
| queue, time zone, calendar, commitment, reply, rerun, nudge, skip, corrupt, future | no match |
| stop | red-capable-repro and other generic stop entries (not this job) |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| sequence-date-math-with-shift | The heart of the plan: business days, holidays, the overdue shift, skipped-not-missed steps, stop rules and the account-wide reply stop. | `references/sequence-math.md`; sequence code in `scripts/plan_day.py` |
| derive-state-from-append-only-log | The worked step and every stop come from `log/activity.csv`, never from a stored next-due field. | `references/sequence-math.md` |
| flat-score-guard | Extra touches must not look ranked when the scores carry no signal. | "Flat-score guard" in `references/queue.md` |
| explainable-weighted-score | The extra-touch score uses weights from `gtm.json`, and each card now shows the parts behind its score. | "The score" in `references/queue.md`; `card_md` |
| zero-unaccounted-day-close | The close marks every card done, skipped with a reason or no record, lists commitments and seeds tomorrow. | `--close` mode; SKILL.md |
| person-and-account-send-gate | Extra touches and steps respect the book's email, call and LinkedIn gates, with the same checks applied for an older book. | "Who is eligible" in `references/queue.md` |
| why-now-or-weak-case | "No prep line, no dial", and a card that quotes a dated fact now shows the source to open first. | `references/queue.md`, `references/sequence-math.md`; `quoted_source` |
| preserve-missingness | A future or offset-less timestamp is reported as a data problem; an unknown last touch is not treated as old or new. | `references/sequence-math.md`, `references/call-blocks.md` |
| exact-target-readback (variant) | Calls are placed only around busy times read from the calendar file, with UTC offsets, never from a free/busy guess. | `references/call-blocks.md` |
| rebuild-keeps-user-edits (variant) | A same-day rerun keeps the user's `skip_reason`, outcomes and added columns, and lists entries whose card is gone. | SKILL.md rerun rule |

## Declined

| Mechanic | Reason |
| --- | --- |
| idempotent-state-with-atomic-replace | daily-plan keeps no state of its own between runs; each plan file is rewritten whole from inputs. |
| strategy-ladder-first-match, reactivation-by-own-rhythm, signal-weight-recency-expiry | Decided upstream by account-book, play-build and signal-score; read only. |
| exact-write-preview, preview-save-publish-separation | No writes to any outside system happen here. |
| learner-knowledge-ledger, explicit-prune-and-append, multidimensional-risk, gather-first-score-later, stop-at-user-owned-render-gate and other single-word matches | Different jobs. |

## Conflicts resolved

- Display order versus who gets the slot: slots go by prep line, then call before LinkedIn, then score; the block order only arranges the page. A callable buyer is never pushed out by a LinkedIn-only person.
- Reruns versus user edits: the plan is regenerated, but the user's entries are merged back by card key, and orphaned entries are listed rather than dropped.

## Gaps found and fixed in this pass

- Cards showed only a total score. Each card now shows the parts (value times weight), hidden when the scores are flat. Test: `test_score_shows_its_parts`. Example `expected/2026-10-20.md` regenerated.
- A card quoting the enrollment's dated fact did not show its source. Cards now carry `source` with a line to open it before the touch. Test: `test_quoted_fact_shows_its_source_to_open`.

## Acceptance checks

`tests/test_gtm_daily_plan.py` (35 tests), including `test_business_days_skip_weekends_and_holidays`, `test_overdue_step_is_planned_today_with_a_shift_note`, `test_reply_stops_the_person_and_the_whole_account`, `test_flat_scores_fall_back_to_the_fact_ladder`, `test_callable_buyer_beats_a_linkedin_only_person_at_the_same_account`, `test_lasting_stop_outcomes_end_every_touch`, `test_rerun_keeps_skip_reasons_and_your_own_columns`, `test_close_accounts_for_every_card` and `test_example_matches_expected_and_inputs_are_untouched`. `check_skill.py` on the skill folder.

## Open gaps

None found in this pass. Not tested: behavior in a fresh session after these edits.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: staged-state-gates, person-and-account-send-gate (status checked again).

Changed:

- Sequence steps and extra touches stop at any account whose status is `live_deal`, `hold` or `archived`, whatever the book's strategy.
- `has_deal` left the default tie-break order (code and example config).
- Ask, don't guess: `--today` is optional; with none, the plan uses today in `daily.user_timezone` and says so at the top.
- "Do first" names `no_prep` cards correctly; "legal hours" became "default calling window" with a note on stricter state rules; the Report lists `plan/<date>-unmatched.csv`.

Checks: `tests/test_gtm_daily_plan.py` (LiveDealTests, StatedDefaultTests); `tests/test_gtm_shared.py` live-deal chain; example expected files unchanged.

Second review: an AI-assisted check pass followed on Oct 22 (findings fixed below).
