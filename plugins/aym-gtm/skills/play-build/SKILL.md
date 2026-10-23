---
name: play-build
description: Design and fill one outbound play from the account book. Decides who qualifies, who at each account gets the touch, how many start a day and when it stops, and writes a proposed enrollment list with every drop counted. Types are signal, event, reactivation, multithread and blitz, with an optional holdout. Use for "build a play", "who goes into this sequence", "set up a win-back play", "invite people to our event" or "who qualifies for this campaign". Not for lists, the book, signals, messages or daily plans. Never enrolls anyone.
---

# Play build

A play answers four questions: who qualifies, who at each account, how many a day, and when it stops. This skill writes those answers to files. You approve each row. Nothing is enrolled, sent or written to any system.

## If the script cannot run

This skill's results come from `scripts/build_play.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write `enroll.csv`, `funnel.md`, `report.md` or `state.json` by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/build_play.py --workspace <workspace> --play <workspace>/plays/<play_id>/play.json --today YYYY-MM-DD`.

## Inputs

In the commands below, `<skill-dir>` is this skill's folder and `<workspace>` is the user's GTM workspace (default `./gtm`).

- `book/people.csv` and `book/accounts.csv` from account-book. The book's gates (`send_ok`, `call_ok`) and each account's `strategy` are used as they are.
- `gtm.json`: the `play` section (defaults for caps, seat order, quiet rules), stop statuses and tags. Every number is an editable default, not a standard.
- `plays/<play_id>/play.json`: the play itself. See [play.json](references/play-json.md).
- By type: `signals/scored.csv` (signal), an events CSV (event), `log/activity.csv` (reactivation, multithread, recent touches), `outreach/sequences.json` (sequence length and variables). Without `sequences.json` the script assumes a 10-day sequence (`play.default_sequence_days`) and says so under "Needs you"; event cutoffs then use that guess.
- Optional `plays/<play_id>/overrides.csv`: your manual adds and removals, each with a reason.

When the user has no workspace, offer the made-up example in [assets/example](assets/example/README.md). Customer or employer data stays where the user may keep it.

## Steps

1. **Agree the play.** Ask what triggers it, who it is for, which sequence, the channel (email, call or any), the start and end dates and the daily cap. These answers decide who gets contacted, so a missing one is never filled with a guess: ask, and stop until the user answers. Nobody being there to answer is not an answer. Suggest the values from `gtm.json` `play` when the user wants a starting point. Write `plays/<play_id>/play.json` with what they agreed; the script refuses a play without `channel`, `start`, `daily_cap` or `sequence` and writes nothing. Pick the type with [play types](references/play-types.md).
2. **Run it:**
   `python3 <skill-dir>/scripts/build_play.py --workspace <workspace> --play <workspace>/plays/<play_id>/play.json --today YYYY-MM-DD`
3. **Read the funnel** (`plays/<play_id>/funnel.md`). Every person in the book is counted at the start, and every rule shows how many it removed and why. See [eligibility rules](references/eligibility.md). If a rule removes more than expected, fix the data or the rule, not the count.
4. **Walk the user through `enroll.csv`.** Proposed rows have a rank, a seat and a start date. Dropped rows at in-scope accounts carry `drop_reason`. The user writes `yes` or `no` in `approved`. Only approved rows are worked by daily-plan.
5. **Record overrides.** When the user adds or removes someone by hand, write a row in `overrides.csv` (`person_id, action, reason, date`) and rerun. Hard rules still apply to adds: stop statuses, opt-outs and the gate. An add whose reason suggests a live conversation (a demo request, a reply, a meeting) is still proposed with `trigger_fact` blank, and "Needs you" says to reply by hand first. The same reason used twice comes back as a rule idea in `report.md`.
6. **Rerun as the book changes.** Approved rows keep their seats and start dates, and what the user typed (`approved`, filled variables) stays. A row approved earlier that is now blocked is flagged on every run until the user clears `approved`. When a play finds nobody new for `max_quiet_runs` runs in a row, the report says to retire it or change its rules.

## Rules that matter most

- **Every drop is counted with a reason.** Nobody disappears from a play without a line in the funnel, and the funnel checks that the start count minus every drop equals the proposed count. A failed check is a bug to report before approving anything.
- **One live play per person.** Someone already in a sequence or approved in another play that is still running is dropped and listed as "reply in that thread instead". People in an open conversation are left to you.
- **The book's gate decides who may be touched, and the account's own status is checked again.** Excluded, on-hold and live-deal strategies stay out, and so does any account whose `status` is `live_deal`, `hold` or `archived`, whatever its strategy says. An account owned by someone else is a counted drop.
- **An optional holdout measures the play.** `holdout_share` (default 0) keeps that share of eligible accounts untouched, picked by a stable hash of the play id and account id, so the same accounts stay out on every rerun. It is applied after seat choice, so each held-out account contributes the seats that would have been touched, each a counted drop with the reason "holdout"; an override cannot add someone back at a held-out account, and funnel-review compares the play with its holdout.
- **One person per account per day,** at most `per_account_cap` per account, at most `daily_cap` a day, round-robin across accounts in rank order.
- **Signal seats follow the signal.** A named new leader gets the touch. Never the person who left. Research-interest signals are timing only and are never quoted.
- **Only confirmed facts are quoted.** When signal-score flags that the source may be about another company, or the named leader is not in the book, `trigger_fact` stays blank and "Needs you" says what to confirm. The named leader's own line says "you", never their name.
- **Reactivation is about rhythm, not silence.** "Quiet" means past that account's own usual gap, and nobody touched in the last few days is proposed, even at a lost-deal account. Rank by past value. The first touch names the gap and does not pitch. Any reply, including an out-of-office, pauses; a complaint stops.
- **Event plays finish before the event.** The last start date leaves room for the whole sequence. Tentative events wait.

## Report

Tell the user: the files written; proposed count and how many are new; the biggest drops in the funnel; everything under "Needs you" in `report.md` (approvals, sources to open before the first touch, blank variables, missing named leaders, people to reply to in an existing thread, people you added who need a reply by hand first, rows that were approved and are now blocked); rule ideas from overrides; whether the play is still finding people. Say plainly that nothing was enrolled, sent or written to a CRM or sequencer.
