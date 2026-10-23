---
name: signal-score
description: "Score dated buying signals (new leaders, leader gaps, job posts, funding, growth, intent) per account, decide which accounts are playable now, and write one sourced why-now line and the seat to contact for each, with a fit-by-timing view. Use to score signals, find who has a real reason to hear from you this week, rank accounts by timing, write why-now lines, or turn job posts and news into a call list. Not for the ICP (icp-define), cleaning data (data-quality), the book (account-book) or messages (outreach-draft). It never enrolls anyone."
---

# Signal score

Turn dated public events into a short, honest list: which accounts have a real reason to hear from you now, the one fact to point to, and which seat to contact. Timing beats a cold list, but only when the fact is real, dated and still fresh.

This skill reads files and writes files. It never sends a message, enrolls anyone, or writes to a CRM.

## If the script cannot run

This skill's results come from `scripts/score_signals.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write `signals/scored.csv`, `signals/signals.csv` or `signals/report.md` by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/score_signals.py --workspace <workspace> --today YYYY-MM-DD`.

## Inputs

All paths are inside the GTM workspace (default `./gtm`).

- `input/accounts.csv`: the accounts you own or target, with `domain`, `other_domains`, `status`, `relationship` and the fields the ICP uses (`employees`, `industry`, `country`, optional `tech`).
- `signals/raw/<YYYY-MM-DD>/*.csv`: raw signal pulls, one folder per pull date, with columns `signal_id, account_name, domain, type, event_date, summary, source_url, person_name, person_title`. Keep these files exactly as pulled. The date folder is when you pulled; `event_date` is when the thing happened.
- `gtm.json` (optional): the `signals` section sets the types, weights, expiry windows, recency bands and seats. Missing settings use the defaults in [scoring](references/scoring.md). They are starting points to tune, not standards.

If there are no raw pulls yet, help the user gather some first. [Gathering signals](references/gathering-signals.md) lists the signal types, where to find each one for free, and how to fill the columns.

## Steps

1. **Check the inputs.** Confirm the accounts file and at least one dated raw folder exist. Ask for the scoring date if the user has not given one. Use today's date for a live run.
2. **Run the scorer.** `<skill-dir>` is this skill's folder; `<workspace>` is the user's GTM workspace.
   `python3 <skill-dir>/scripts/score_signals.py --workspace <workspace> --today YYYY-MM-DD`
   It matches signals to accounts, drops expired ones, scores each account, applies the playable gate, and writes `signals/scored.csv`, `signals/signals.csv` and `signals/report.md`.
3. **Read the report, not just the scores.** Look at "Not used" first. Unmatched rows usually mean a missing domain on the account or a new account worth adding. Skipped rows mean a missing date, a missing source or an unknown type. Never edit a raw pull or an output. Save a corrected row, with the same `signal_id`, in a new dated pull folder and rerun: the newest pull wins. Also read "Check before use": a signal matched by domain whose company name differs from your account needs a human to confirm it is the same company.
4. **Check each playable why-now line.** It must state only what the source says, with its date. Follow the rules in [why-now lines](references/why-now.md). If a line overstates the source, save a corrected row with a summary that matches the source, same `signal_id`, in a new dated pull folder, and rerun.
5. **Hand off.** Give the user the playable list, the held list with reasons, any "check" notes, and the reminder to open every source link before the first touch. account-book uses `scored.csv` for strategy; outreach-draft writes the first touches.

## How scoring works (short version)

- Match by domain or other domain first, then by exact company name with legal endings like Inc or LLC removed. Never a fuzzy guess. A name or domain that fits two accounts is reported, not matched.
- Each signal type has a weight and an expiry window counted from `event_date`. Expired signals are kept in the trace but do not score.
- Recency multiplies the weight: 1.0 up to 30 days old, 0.7 up to 90, 0.4 after that. Job posts expire after 60 days and research interest after 30 by default, because a role is usually filled within weeks.
- Account score = the sum, over signal types, of that type's best weight x recency. Two job posts do not double count; a job post plus a new leader does.
- Full math and the playable gate: [scoring](references/scoring.md).

## The playable gate

An account is playable only when all of these hold:

- its status is not hold, live deal or archived
- its relationship is not one the ICP excludes (`icp.exclude_relationships` in `gtm.json`: by default competitor, customer, partner), and never a company whose parent makes the decision
- it fits the ICP, by the shared fit rule (`scripts/gtm_fit.py`, the same file icp-define, data-quality and account-book use). Out is held with the reason; a blank field the rule needs is held as "fit unknown: enrich first"
- it has at least one live signal with a weight above 0 that you can cite: research interest alone is held as "intent only: find a citable reason first"

Layoffs carry weight 0. They are context, never a reason to reach out. Topic intent counts as timing, but it is never quoted or hinted at in a message, so it never makes an account playable on its own.

## Fit by timing

Each scored account also gets a `quadrant`: fit is the gate, a citable live signal is the timing. `act` (fits, citable reason now), `nurture` (fits, nothing citable yet), `verify` (a fresh signal but the fit is out or unknown: check the fit first) and `suppress` (neither). Status is separate: an `act` account on hold is still not playable. The report lists the accounts in each quadrant with what to do.

## Outputs

- `signals/scored.csv`: one row per account with a matched signal. Columns: `account_id, name, score, top_type, playable, why_not, why_now, source_url, event_date, seat, live_signals, signals, check, quadrant`. Sorted playable first, then score, then account id. Accounts with no matched signal are not listed.
- `signals/signals.csv`: every raw row with its status (live, expired, unmatched, skipped, duplicate), the reason, age, weight, recency factor, value and any check note. Any score can be traced back to its rows.
- `signals/report.md`: counts, the playable table, the fit-by-timing table, held accounts with reasons, signals to check before use, rows not used, and the before-first-touch checklist.

## Boundaries

- Never invent a signal, a date or a source. A row without a source link or a valid date is skipped.
- Never change files under `signals/raw/`. The scorer refuses to write there.
- Seat is a role, not a person, except for a named new leader. For a leader gap, never contact the person who left.
- Customer or employer data stays where the user is allowed to keep it. The example workspace uses made-up companies only.

## Report

Tell the user: the files written, the counts (read, live, expired, unmatched, skipped, duplicate), the playable accounts with score and why-now line, the held accounts and why, any inputs to fix, and that they must open each source before the first touch. Say plainly that nothing was sent and no system was changed.

## Try it

`python3 <skill-dir>/scripts/score_signals.py --workspace <skill-dir>/assets/example --today 2026-10-20 --out <any empty folder>` runs on a made-up workspace with fresh, old, expired, unmatched, intent-only, weight-0, held and duplicate signals.
