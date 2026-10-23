---
name: funnel-review
description: "Review outbound results honestly from the activity log: reply, meeting and call rates with sample sizes and 95% ranges, results by segment, meetings by first-touch week, a volume/rate/mix split of why meetings moved, pre-registered tests, play holdouts and the quota worked back from the target. Ends with at most three sized actions or 'Nothing needs to change.' Use for how outbound is doing, a periodic review, a test winner, or why meetings moved. Not for deal pipeline or forecasts, logging, daily plans or plays. Never sends or changes anything."
---

# Funnel review

Say what is working, how sure you are, and what to change, without dressing up small numbers. A rate with five people behind it is an anecdote. A rise in meetings can hide every segment getting worse. This skill keeps both honest.

It reads files and writes a report. It never sends a message, enrolls anyone, or writes to a CRM.

## If the script cannot run

This skill's results come from `scripts/funnel_report.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write a funnel report or metrics file by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/funnel_report.py --workspace <workspace> --today YYYY-MM-DD --period-days 30`.

## Inputs

All paths are inside the GTM workspace (default `./gtm`).

- `log/activity.csv` (required): one row per touch or outcome, in the shared log format described in [formulas](references/formulas.md#the-activity-log), with the rows this skill counts in [what counts as what](references/formulas.md#what-counts-as-what).
- `book/people.csv` and `book/accounts.csv` (optional): used to put each person in a segment.
- `plays/*/enroll.csv` (optional): approved enrollments, used to credit plays, and holdout rows from play-build, used to compare a play with the accounts it left alone.
- `funnel/tests.json` (optional): opener and angle tests, written before results came in.
- `funnel/targets.json` (optional): commit and stretch meeting targets.
- `funnel/changes.csv` (optional): `date, change, area` for every change to copy, scripts, lists or timing.
- `gtm.json` (optional): the `funnel` section sets floors, bands, test minimums, minutes per touch and how to segment (`segment_by`: segment, persona, play, industry or tier). Defaults are starting points to tune, not standards.

## Steps

1. **Check the log.** Confirm `log/activity.csv` exists. Use the period and last day the user names. With none named, use 30 days ending today and say so in the report: it is read-only, so a stated default is fine.
2. **Run the review.** `<skill-dir>` is this skill's folder; `<workspace>` is the user's GTM workspace.
   `python3 <skill-dir>/scripts/funnel_report.py --workspace <workspace> --today YYYY-MM-DD --period-days 30`
   It writes `funnel/report-<today>.md` and `funnel/metrics-<today>.csv`.
3. **Read the data checks first.** Excluded rows (blank or future timestamps, unknown values, no person) and incomplete rows tell you how far to trust the rest. If logging gaps are large, fixing the log comes before any other conclusion.
4. **Read each number with its label.** Only "measured" rates get a percentage. Everything else is "N of M". See [formulas](references/formulas.md) for every formula, denominator and floor.
5. **Read lagged meetings and cohorts.** Meetings often land weeks after the first touch. "Booked from earlier touches" counts meetings this period from people first touched before it, kept out of the rate. The cohort table groups people by the week of their first touch; judge only weeks marked mature. See [formulas](references/formulas.md#lag-and-cohorts).
6. **Explain movement carefully.** Use the volume/rate/mix table for why meetings moved; meetings from a brand-new segment sit on their own line. Give the count and the cause separate confidence, list other possible causes, and credit no single change when several shipped together. See [explaining movement](references/explaining-movement.md).
7. **Read the tests and holdouts.** A leader is named only when every arm has its minimum, and "clear" only when the ranges do not overlap. Rows where the caller used a different arm than the person was assigned are reported apart. A play with a holdout shows its meeting rate next to the holdout's; only non-overlapping ranges count as a clear difference. See [tests and quota](references/tests-and-quota.md).
8. **Hand off the actions.** At most three, each with its number and size, or "Nothing needs to change." Never pad to three.

When the user wants a new test, write it into `funnel/tests.json` with them before any calls or emails go out: one variable, the arms, the metric, the minimum per arm, today as `registered`, and a start date.

## Rules that do not bend

- Every rate shows its counts. No rate below the floor (default 20). Under 5 it is an anecdote.
- Each segment's rate uses only the people that segment could reach. A wider total is labeled context.
- Every pattern claim says "N of M". One case is never a rate.
- Explanations are inferences until tested. Several changes at once means none is credited.
- Unknown rates are flagged, never guessed, including in the quota.

## Outputs

- `funnel/report-<today>.md`: scope and limits, headline numbers (prior vs current, including meetings booked from earlier touches), the segment table, the cohort table, play holdouts, why meetings moved, tests, quota and levers, patterns, data checks, actions.
- `funnel/metrics-<today>.csv`: one row per rate (overall, segment, test and cohort week) with `period, scope, metric, numerator, denominator, rate, ci_low, ci_high, label`.

## Boundaries

- Deal-stage pipeline, forecast categories and won/lost analysis belong to a sales or CRM tool. This skill covers the top of the funnel: touches, replies, connects, conversations and meetings.
- The script refuses to write into `log/`, `book/`, `input/`, `plays/` or `signals/`, and never writes over an input file.
- Customer or employer data stays where the user is allowed to keep it. The example workspace uses made-up people and companies only.

## Report

Tell the user: the files written, the period and row counts, excluded rows and why, the headline rates with their labels, what moved and the honest confidence in why, each test's verdict and next-up arm, the quota numbers or "unknown", and the actions (or "Nothing needs to change."). Say plainly that nothing was sent and no system was changed.

## Try it

`python3 <skill-dir>/scripts/funnel_report.py --workspace <skill-dir>/assets/example --today 2026-10-20 --period-days 30 --out <any empty folder>` runs two 30-day periods of made-up Ledgerline activity with an opener test, an angle test, targets, two logged changes and a few bad log rows. The expected output is in `assets/example/expected/`.
