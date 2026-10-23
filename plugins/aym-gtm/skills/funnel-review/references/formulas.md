# Formulas, floors and labels

Every number in the report comes from one of the formulas below. They are written as formulas only. The defaults live in `gtm.json` under `funnel` and are starting points to tune, not standards.

## Periods

- Current period: the `--period-days` days (default 30) ending on `--today`, both ends counted.
- Prior period: the same number of days just before it.
- A row belongs to the day in its own timestamp offset. `2026-10-20T23:30:00-04:00` is October 20.

## The activity log

`log/activity.csv`, shared by daily-plan, outreach-draft, crm-sync and this skill:

`activity_id, timestamp, person_id, account_id, channel, direction, sequence, step, play_id, angle, opener, outcome, notes, source`

- `timestamp`: ISO 8601 with a UTC offset, such as `2026-10-20T14:05:00-04:00`.
- `channel`: `email`, `call`, `linkedin` or `meeting`. `direction`: `out` or `in`.
- `outcome`: `sent`, `connected`, `no_answer`, `voicemail`, `bad_number`, `gatekeeper`, `replied`, `interested`, `not_now`, `not_interested`, `booked`, `bounced`, `opt_out`, `wrong_person` or `left`.
- `angle` (emails) and `opener` (calls) name the arm used, for tests. `play_id` credits a play.

## What counts as what

The activity log columns and allowed values are in the shared layout (`log/activity.csv`).

| Term | Rows |
|---|---|
| touch | `direction` out, `channel` email, call or linkedin |
| email sent | channel email, direction out, outcome `sent` |
| dial | channel call, direction out |
| connect | a dial with outcome `connected`, `interested`, `not_now`, `not_interested`, `booked` or `wrong_person`. `bad_number`, `gatekeeper`, `no_answer` and `voicemail` are not connects. |
| conversation | a dial with outcome `interested`, `not_now`, `not_interested` or `booked` |
| email engagement | channel email with outcome `replied`, `interested`, `not_now`, `not_interested` or `booked` |
| booked | any row with outcome `booked` |
| bounce | a person emailed in the period whose email `bounced` row comes after their first send in the period, counted once per person |

## Lag and cohorts

A meeting often lands days or weeks after the first touch, so a calendar period can miss it.

- **Booked from earlier touches:** people booked in the period who were not touched in it, but were touched in the `funnel.lag_lookback_days` (default 30) before it. Shown in the headline table, kept out of every rate.
- **Cohorts:** each person counts once, in the week (Monday to Sunday) of their first outbound touch in the log, with every meeting booked since. The table covers the last `funnel.cohort_weeks` (default 8) weeks. A week is mature `funnel.cohort_maturation_days` (default 21) days after its last day; judge only mature weeks, because younger ones are still filling. Rates use the same floors and ranges as everything else.

## Rates

| Rate | Numerator | Denominator |
|---|---|---|
| Reply rate | distinct people emailed in the period who engaged by email in the period | distinct people emailed in the period |
| Meeting rate | distinct people touched in the period who were booked in the period | distinct people touched in the period |
| Connect rate | connects | dials |
| Conversation rate | conversations | connects |
| Bounce rate | bounces (people, as defined above, never more than emails sent) | emails sent |

The numerator is always a subset of the denominator. A bounce row for someone not emailed in the period, or dated before their send, is shown as context and kept out of the bounce rate. If a numerator ever exceeds its base, the rate is labeled invalid and no range is computed. A reply from someone who was not emailed in the period, or a booking for someone not touched in the period, is shown as labeled context and kept out of every rate.

## Denominator rule

Each segment's rate uses only the people that segment could reach: its own people emailed or touched. A wider total, such as everyone touched, is never the denominator for a narrower segment. It may appear next to it, labeled as context. The segment table also shows "everyone else's" rate so you compare like with like.

A segment rate far above anything you have seen before usually means the wrong base, not a great segment. Put the rates you trust in `funnel.benchmarks` (for example `{"meeting_rate": 0.03, "reply_rate": 0.05}`); any measured rate at `funnel.benchmark_alarm_factor` (default 10) times its benchmark or more is listed under "Check the base" in the report. Check the base first.

## Sample floors and intervals

| People or events behind the rate | Label | Shown as |
|---|---|---|
| 0 | no data | "no data" |
| fewer than `anecdote_n` (default 5) | anecdote, not a rate | counts only |
| fewer than `min_n_rate` (default 20) | too few to rate | counts only; an observed pattern at most |
| `min_n_rate` or more | measured | rate, counts, 95% range |

- The 95% range is the Wilson interval with z = 1.96. It stays inside 0 to 100% and behaves well with small counts.
- Zero events use the rule of three: the range is 0 to 3/n.
- "Clear change" between two rates means both are measured and their ranges do not overlap. Anything else is "no".

## Evidence labels

- **Measured**: a rate with enough behind it, from the formulas above.
- **Observed pattern**: counted, but too few to rate. Report it as "N of M", never as a percentage.
- **Inference**: an explanation of why something moved. It stays an inference until a test or a clean comparison measures it.

Never turn one case into a rate. Every pattern claim shows "N of M".

## Bounce bands

`funnel.bounce_bands` lists `[upper limit, name]` pairs: by default healthy up to 2%, watch up to 5%, stop above that. A stop band means pause new email volume and verify addresses before sending more.

## Data checks

These rows are excluded and counted in the report:

- blank or unreadable timestamp
- timestamp after `--today` (treated as blank: a date in the future is corrupt)
- a channel, direction or outcome not in the allowed list (never guessed)
- no `person_id`
- person and account disagree: the row's `account_id` is not the account the book has for that person

These rows are kept but counted as incomplete: an email sent with no `angle`, and a row with a `sequence` but no `step`. When excluded and incomplete rows are more than `logging_gap_share` (default 10%) of the log, fixing the logging becomes an action.
