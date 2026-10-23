# Example: one planned day and its close

Everything here is made up. Ledgerline is a fictional company selling spend-management software to finance teams. Domains end in `.example` and phones use the fictional 555-01xx range.

## What is in the folder

- `gtm.json`: the shared Ledgerline config plus a `daily` section. 2026-10-16 is a company holiday.
- `book/`: a small book with send, follow-up and call gates already filled in.
- `plays/signal-2026-10/enroll.csv`: six approved enrollments and one not yet approved.
- `outreach/sequences.json`: one four-step sequence (email, call, reply email, LinkedIn).
- `log/activity.csv`: worked steps, a missed call step, a reply, a row typed with the wrong year, and three rows logged during 2026-10-20.
- `signals/scored.csv`: two playable accounts, used for prep lines.
- `plan/calendar.csv`: a standup, and one row with no UTC offset.
- `expected/`: what the plan and the close should look like.

## Run it on a copy

```bash
cp -r <skill-dir>/assets/example /tmp/gtm-day
python3 <skill-dir>/scripts/plan_day.py --workspace /tmp/gtm-day --today 2026-10-20 --nudge
python3 <skill-dir>/scripts/plan_day.py --workspace /tmp/gtm-day --today 2026-10-20
python3 <skill-dir>/scripts/plan_day.py --workspace /tmp/gtm-day --today 2026-10-20 --close
```

## What you should see

- Marcus's step 3 email was due 2026-10-19 and is planned today, moved 1 business day.
- Hollis's step 2 call sits at 9:30 your time. The standup removes the 10:00 to 10:30 slots.
- Simone's first email needs a human: `trigger_fact` is empty.
- Rowan has no phone, so his step 2 call is skipped, not missed, and his step 3 email is due today on schedule.
- Kenji replied, so his sequence stops, and so does Laila's at the same account.
- Owen, an inbound lead nobody called, is first in the extra touches, at 11:00 his time in Los Angeles.
- At Brightmill and Harborview a callable buyer takes the account's one extra-touch slot ahead of the LinkedIn-only person. Jonas has no time zone, so his call needs a human.
- The row dated 2026-11-30 and the calendar row with no offset are listed as data problems.
- The close finds 3 cards done, lists 6 with no record, and pulls two commitments from the notes on Hollis's call.

To see a skip in the close, write a reason in the `skip_reason` column of `plan/2026-10-20.csv` (for example "out sick") and rerun the close.
