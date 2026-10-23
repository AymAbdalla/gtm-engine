# Sequence math

How `plan_day.py` decides which sequence step is due today for each approved enrollment.

## Where the dates come from

- `plays/<play_id>/enroll.csv` gives `sequence` and `sequence_start` for each approved person (`approved` = `yes`, `drop_reason` blank). A person approved in two plays is planned only from the first play file in name order; the second is reported.
- `outreach/sequences.json` gives the steps. Steps are sorted by `day`, then `order`. Step numbers count from 1 in that order, and the log uses the same numbers.
- A person the book says is in a sequence, but with no approved enrollment, is reported, not planned. Without a start date there is no schedule.

## Business days

- Day `d` lands on `sequence_start + (d - 1)` business days.
- Business days skip Saturday, Sunday and every date in `daily.holidays`.
- A start date on a weekend or holiday rolls forward to the next business day.

Example with `daily.holidays` = `["2026-10-16"]` and a start of Tuesday 2026-10-13: day 1 is 10-13, day 2 is 10-14, day 4 is 10-19 (10-16 is a holiday and 10-17 and 10-18 are a weekend), day 7 is 10-22.

## Worked steps and shifts

- A step is worked when the log has an outgoing row for that person, that sequence and that step number, with any outcome.
- The next step is the one after the highest worked step.
- **Late work shifts the rest.** If step `j` was first worked `n` business days after its due date, every later step moves back by `n` business days. Gaps between steps stay the same size.
- **Overdue today.** If the next step's due date is before today, it is planned today and the card says how many business days it moved. Later steps move with it.

## Steps that cannot be done

A step is skipped, not missed, when its channel cannot be used for this person:

| Channel | Usable when |
| --- | --- |
| email | the book says `send_ok` = yes or `followup_ok` = yes, and no email block tag (default `bounced`) |
| call | `call_ok` = yes, a phone, no call block tag (default `dnc_phone`, `phone_failed`), and a free slot inside 8am to 9pm in the prospect's time zone |
| linkedin | a LinkedIn profile, and no LinkedIn block tag |

A skipped step is listed under "Skipped steps" once it comes due, and the sequence moves straight on to the next step. It does not shift later steps.

## Stops

Checked before any step, using log rows from before today:

- the person's status is in `stop_statuses`, or a tag is in `dnc_tags` or `left_tags`
- the person has an outcome of `opt_out`, `not_interested`, `wrong_person` or `left` at any time, even before the start date. These end every touch, not just one sequence
- the account's `owner` is someone other than you (`daily.owner`, else `play.owner`, else `you`; a blank owner counts as yours). The same rule play-build uses
- the account's own `status` is `live_deal`, `hold` or `archived`, even when the book's strategy says otherwise: a live deal belongs to its owner
- the person has an outcome of `replied`, `interested`, `not_now`, `booked` or `bounced` on or after the start date
- anyone else at the same account has `replied`, `interested`, `not_now`, `not_interested` or `booked` on or after the earlier of the start date and `daily.reply_lookback_days` (default 30) before today: a reply stops the whole account. The account comes from the book, not the log row, so a row with a blank or wrong `account_id` still stops the right account. A row whose account disagrees with the book is listed as a data problem
- every step is worked or skipped: the sequence is finished

A `bounced` outcome from before the start date does not stop the sequence, but every email step is skipped with "email bounced on <date>" and the call and LinkedIn steps go on.
- every step is worked or skipped: the sequence is finished

## Variables

Each step's subject and body are filled from the enrollment's `variables` JSON, plus `first_name`, `last_name`, `title` and `company` (the account name) from the book. Any `{{name}}` left empty makes the card `needs_human`, and the card shows what to fill. Invalid JSON in `variables` also needs a human.

## The activity log

`log/activity.csv` columns: `activity_id, timestamp, person_id, account_id, channel, direction, sequence, step, play_id, angle, opener, outcome, notes, source`.

- `timestamp` needs a UTC offset, such as `2026-10-20T14:05:00-04:00`. A time with no offset, or one after today, is a data problem. The row still counts (a step it logs is worked, a stop outcome still stops), but its date is unknown and it is reported.
- `outcome` must be one of: `sent`, `connected`, `no_answer`, `voicemail`, `bad_number`, `gatekeeper`, `replied`, `interested`, `not_now`, `not_interested`, `booked`, `bounced`, `opt_out`, `wrong_person`, `left`. Anything else is reported and ignored.
- The plan for a date uses only rows from before that date in your time zone. The close uses that date's rows.

A card whose text quotes the enrollment's dated fact (`trigger_fact`) also shows its `source_url`. Open it before the touch; if the page is gone or says something else, do not use the fact.
