# Design record: funnel-review (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries).

## Job

Report what is working in outbound with honest numbers: fixed formulas, rates on the right base with sample sizes and ranges, why meetings moved, pre-registered opener and message tests, a quota model, and at most three actions. The caller reviews a week or a month. It reads files and writes `funnel/` reports only. It declines CRM pipeline and forecast work (left to the sales plugin), planning the day (daily-plan) and building plays (play-build).

## Library queries

| Query | IDs returned |
| --- | --- |
| rate | separate-report-and-repair-modes, rate-with-sample-and-interval, milestone-to-transferable-article, deterministic-first-graph-enrichment, motion-uses-feedback-and-interruption, source-trace-for-claims |
| sample, interval | rate-with-sample-and-interval |
| denominator | reach-based-denominator |
| test | confirm-test-seams, bounded-test-evidence-modes, preregistered-single-variable-test, editorial-rules-need-calibration, skill-authoring-as-release-process, test-cheap-before-production |
| variable | preregistered-single-variable-test |
| bridge, period | volume-rate-mix-bridge |
| causal | measurement-versus-causality |
| comparable | analytics-lineage, measurement-versus-causality |
| lineage | analytics-lineage, simple-workbook-with-lineage, editable-evidence-lineage, claim-vs-measurement-lineage, verify-license-and-lineage |
| cohort, analytics | analytics-lineage |
| measure | skill-evaluation-needs-calibrated-holdouts, stable-task-outcome-evaluation, measurement-versus-causality, start-simple-measure-before-complexity, measure-keep-or-revert, measure-model-acceptance |
| missing, zero | preserve-missingness (plus test and integrity entries), zero-unaccounted-day-close |
| target, action, metric | mixed entries; none beyond the ones selected |
| segment, confidence, quota, benchmark, keep or revert | no match |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| rate-with-sample-and-interval | Small BDR samples must not read as reliable rates: n, Wilson range, rule of three, anecdote label, N of M. | `references/formulas.md`; `rate_cell`, `wilson` |
| reach-based-denominator | Each segment rate uses only who that segment could reach; wider totals are context; a rate far above benchmark now raises "Check the base". | `references/formulas.md`; `base_alarms` |
| volume-rate-mix-bridge | Explains why meetings moved with parts that add up exactly, new segments on their own line. | `references/explaining-movement.md` |
| preregistered-single-variable-test | Opener and message tests are written before results, split by a stable hash, one variable, a minimum per arm. | `references/tests-and-quota.md` |
| measurement-versus-causality | Several changes in one period credit none; count confidence is separate from cause confidence. | `references/explaining-movement.md` |
| analytics-lineage | Every report opens with the periods, inputs, rows used and excluded, and the floors, and every rate names its numerator and base. | "Scope and limits" in the report |
| claim-vs-measurement-lineage, source-trace-for-claims | Every claim carries a label: measured, observed pattern or inference. | `references/formulas.md` labels |
| preserve-missingness | Future, blank and unknown rows are excluded and reported; an unmeasured rate makes the quota "unknown", never a guess. | `references/formulas.md`, `references/tests-and-quota.md` |
| measure-keep-or-revert | Email angles are kept after the minimum if they beat the others, else rewritten once, then cut. | `references/tests-and-quota.md` |

## Declined

| Mechanic | Reason |
| --- | --- |
| start-simple-measure-before-complexity, measure-model-acceptance, skill-evaluation-needs-calibrated-holdouts, stable-task-outcome-evaluation | Model and skill evaluation, not funnel reporting. |
| editable-evidence-lineage, simple-workbook-with-lineage | Workbook delivery; this skill writes Markdown and CSV. |
| zero-unaccounted-day-close | Belongs to daily-plan. |
| separate-report-and-repair-modes and other single-word hits | Different jobs; funnel-review is report-only by design. |

## Conflicts resolved

- "Exactly three actions" versus honesty: the report gives at most three, each with its number and size, and never pads; with nothing qualifying it says "Nothing needs to change".
- Approved rows that play-build later blocked: they still own touches made before the block, but a live approved row in another play wins for attribution.

## Gaps found and fixed in this pass

- The config had a `benchmarks` slot and the reference promised a wrong-base warning, but the script never checked it. `base_alarms` now lists any measured rate at `funnel.benchmark_alarm_factor` (default 10) times its benchmark under "Check the base". Test: `test_rate_far_above_benchmark_asks_to_check_the_base`. New script default `benchmark_alarm_factor` (not yet in the shared `gtm.json`; the lead adds it when the sections are next merged).

## Acceptance checks

`tests/test_gtm_funnel_review.py` (28 tests), including `test_counts_and_rates_follow_the_written_formulas`, `test_wilson_interval_matches_known_values`, `test_zero_events_use_the_rule_of_three`, `test_denominator_rule_per_segment`, `test_volume_rate_and_mix_add_up_exactly`, `test_leader_only_when_every_arm_has_the_minimum`, `test_at_most_three_actions_each_with_a_size` and `test_example_matches_the_expected_report`. `check_skill.py` on the skill folder.

## Open gaps

None found in this pass. Not tested: behavior in a fresh session after these edits.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: analytics-lineage (cohorts), rate-with-sample-and-interval, skill-evaluation-needs-calibrated-holdouts (holdout comparison).

Changed:

- Default period: `--period-days` defaults to 30.
- "Booked from earlier touches" in the headline, kept out of the rate (`funnel.lag_lookback_days`, default 30).
- Cohort table by first-touch week with a maturation window (`funnel.cohort_maturation_days`, default 21; `cohort_weeks` 8), also in the metrics CSV.
- Play holdouts: worked vs holdout meeting rates with ranges, from play-build's holdout rows.
- The log format is described inside the skill (`references/formulas.md`).

Checks: `tests/test_gtm_funnel_review.py` (LagAndCohorts, HoldoutLift); example expected report and metrics refreshed.

Second review: an AI-assisted check pass followed on Oct 22 (findings fixed below).
