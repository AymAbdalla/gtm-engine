---
name: daily-plan
description: Turn approved play enrollments, sequence templates and the activity log into today's work file (sequence steps due, extra calls and LinkedIn touches in a weighted queue, call slots in each prospect's local time), give a one-line morning nudge, and close the day so every card ends done, skipped with a reason, or no record. Use for "plan my day", "what's due in my sequences", "build today's call list", "morning nudge" or "close the day". Not for plays, copy, scoring, the book, CRM sync or results. Never sends, dials or enrolls.
---

# Daily plan

Give the user one file that says what to do today and in what order, then make sure nothing falls through by evening. The plan is built from files the other aym-gtm skills write. This skill writes only under `plan/`. It never sends an email, dials a number, enrolls anyone or writes to a CRM.

## If the script cannot run

This skill's results come from `scripts/plan_day.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write a plan, close or nudge file in `plan/` by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/plan_day.py --workspace <workspace> --today YYYY-MM-DD`.

## Inputs

All paths are inside the GTM workspace (default `./gtm`). `<skill-dir>` is this skill's folder.

- `book/people.csv` and `book/accounts.csv` from account-book. The plan trusts the book's `send_ok`, `followup_ok` and `call_ok` columns. If they are missing, rebuild the book first.
- `plays/<play_id>/enroll.csv` from play-build. Only rows with `approved` = `yes` are worked.
- `outreach/sequences.json`: the sequence templates (outreach-draft owns the format).
- `log/activity.csv`: one row per touch or outcome, newest row wins.
- Optional: `signals/scored.csv` (signal-score) for prep lines and the signal score, and `plan/calendar.csv` (`start, end, title`, times with a UTC offset) for your own busy times.
- `gtm.json`, section `daily`: your time zone, holidays, call blocks, calling window, weights and caps. Missing keys use the defaults in [config](references/config.md). They are starting points, not standards.

## Steps

1. **Check the inputs.** Confirm the book, at least one approved enrollment or a book worth working, and the sequences file. With no date given, the plan uses today in `daily.user_timezone` and says so at the top; this is a read-only plan, so a stated default is fine. Confirm `daily.user_timezone` is right; every call time depends on it.
2. **Plan the day.**
   `python3 <skill-dir>/scripts/plan_day.py --workspace <workspace> --today YYYY-MM-DD` (leave out `--today` to plan today)
   It writes `plan/YYYY-MM-DD.md` (cards with a checkbox and an outcome line) and `plan/YYYY-MM-DD.csv`. The plan uses only log rows from before today, so a rerun later in the day gives the same plan. A rerun keeps any `skip_reason` (and any column of your own) already written in the plan CSV and says how many it kept. If a card you wrote on no longer exists (the person moved to another card or was stopped), your entry is listed under "Entries kept from the last run that no longer match a card" and kept in `plan/YYYY-MM-DD-unmatched.csv`; it goes back onto its card if the card returns. The `.md` file is rewritten, so log outcomes in `log/activity.csv`, not in the `.md`.
3. **Read it with the user, top down.** Start with "Do first". Then:
   - cards marked `needs_human`: fill the missing variable or check the time zone before they can be worked
   - cards marked `no_prep`: no prep line, no dial. Find one real reason first, or leave them at the bottom
   - "Skipped steps": steps that could not be done. They are not missed and do not hold up the sequence
   - "Stopped sequences": a reply, a status or a tag ended them. A person takes over replies
   - "Data problems": fix these at the source
4. **Morning nudge (optional).** For a scheduled routine or a quick start:
   `python3 <skill-dir>/scripts/plan_day.py --workspace <workspace> --today YYYY-MM-DD --nudge`
   It prints one line, or one line starting `FAILED:` with the reason, and writes nothing.
5. **During the day,** the user logs each touch in `log/activity.csv` with the sequence, the step and the outcome. Outcomes come from the fixed list in [sequence math](references/sequence-math.md); never invent new ones.
6. **Close the day.**
   `python3 <skill-dir>/scripts/plan_day.py --workspace <workspace> --today YYYY-MM-DD --close`
   Every planned card ends as done (a log row exists), skipped (the user wrote a `skip_reason` in the plan CSV) or "no record". Cards with no record are listed first. Ask the user to log them or give a reason, then rerun the close until no record is zero. The close also lists commitments from today's log notes ("we owe: ... by YYYY-MM-DD", "they owe: ...") and tomorrow's top 3.

## How the plan is built

- **Sequence steps:** step day `d` lands on the enrollment's start date plus `d - 1` business days, skipping weekends and `daily.holidays`. A step worked late pushes every later step back by the same number of business days. An overdue step is planned today with a note. One card per person per day. Detail: [sequence math](references/sequence-math.md). Email cards are filled from the template and say "copy: filled from the template; read it before sending". To check that copy, run outreach-draft's copy lint on it yourself; this skill never runs another skill's script.
- **Stops:** a stop status, an opt-out or left tag, an opt out, not interested, wrong person or left outcome at any time, an account owned by someone else, an account whose own `status` is `live_deal`, `hold` or `archived` (checked even when the book's strategy says otherwise), or a replied, interested, not now, booked or bounced outcome since the start ends the person's sequence. A reply or meeting from anyone at the account (the book's account, looking back `daily.reply_lookback_days`) stops every sequence there.
- **Extra touches:** people in the book who are not in a sequence, pass the book's call or LinkedIn gate, have no lasting stop outcome in the log, and are at accounts you own, get a weighted score. Each account's slot goes to the best candidate, and a callable buyer beats a LinkedIn-only person. Cards are then shown in blocks: inbound never worked, warm, LinkedIn only, volume. When the scores are too close to mean anything, the plan says so and orders by plain facts instead. Detail: [queue](references/queue.md).
- **Call slots:** calls fill your call blocks, first inside the prospect's preferred hours, then anywhere inside the default calling window, 8am to 9pm their time. That window is the US federal default for telemarketing; some states are stricter, so set `daily.call_window` for where you call. Busy times from your calendar are removed. A call with an unknown time zone needs a human. Detail: [call blocks](references/call-blocks.md).

## Boundaries

- Never send, dial, enroll or write to a CRM. The plan is a list for a person.
- Never mark a card done without a log row. "No record" stays loud until the user resolves it.
- A timestamp with no UTC offset, or one after today, is a data problem. It is reported, never silently trusted.
- Do not change enrollments, the book or the log. Fix those with play-build, account-book or by hand.

## Report

After planning: the date used (and that it was today by default, when no date was given), the "Do first" line, card counts by block, needs-you items, skipped steps, stopped sequences and data problems, and the file paths, including `plan/<date>-unmatched.csv` when it was written. After closing: done, skipped, carried and no-record counts, commitments, tomorrow's top 3, and what is still unresolved. Say plainly that nothing was sent, dialed or enrolled.
