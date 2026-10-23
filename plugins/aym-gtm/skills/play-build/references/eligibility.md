# Eligibility rules

The funnel starts with everyone in the book. Each rule removes people and counts them with the reason. People at accounts outside the play's scope are counted in the funnel only. Everyone dropped at an in-scope account also gets a row in `enroll.csv` with `drop_reason`.

| # | Rule | Drops when |
|---|---|---|
| 1 | Account in scope | The account does not fit the play type (see play types). A sequence already under way in this play keeps running for that person even when the account leaves the scope. |
| 2 | Strategy allows outbound | The account `status` is `live_deal`, `hold` or `archived`, or its strategy is `excluded`, `hold` or `live`. The status is checked even when the book's strategy says otherwise. Live deals belong to the deal owner. |
| 3 | Yours to work | The account `owner` is someone other than `play.owner`. A blank owner counts as yours. |
| 4 | No stop | The person's status is in `stop_statuses`, they carry an opt-out tag (`dnc_tags`) or a left tag (`left_tags`), or the log ever shows a stop outcome for them (`play.stop_outcomes`: opt_out, not_interested, wrong_person, left; plus `play.email_stop_outcomes`, bounced, on email plays). |
| 4b | No open conversation | The log shows a conversation outcome (`play.conversation_outcomes`: replied, interested, not_now, booked) in the last `play.conversation_days` days. A person handles a conversation, not a new sequence. |
| 5 | One live play per person | They are already in a sequence, or approved in another play whose sequence has not ended. Another play stops holding the person once its last step date has passed or a stop or conversation outcome ended it there (rules 4 and 4b still apply). They are listed under "reply in that thread instead". People approved in this play stay. |
| 6 | Channel gate | `send_ok` (email), `call_ok` (call) or either (any) is not `yes` in the book. The book's reason is kept. |
| 7 | Persona | The person's persona is not in `play.personas` (or the event's personas). With no list, anyone without a persona drops as not a buyer. |
| 7b | Near the event | Event plays only: the phone area code is not in the event's `area_codes`. |
| 7c | New lane | Multithread plays only: the person is already engaged or sits in a lane that is. A person whose sequence in this play is under way is not dropped for engaging. |
| 8 | Not touched recently | Their last outbound touch was within `recent_touch_days`. Reactivation plays apply it too, with `reactivation.recent_touch_days`, even at accounts tagged `lost_deal` or set to re-engage. Touches from this play's own running sequence do not count. |
| 9 | Your removals | `overrides.csv` removes them. |
| 9b | Holdout | Only when `holdout_share` is above 0: the account falls in the holdout (a stable hash of `<play id>:<account id>` below the share). It runs after seat choice (rule 10), so only the seat that would have been touched is held out and the holdout counts the same unit as the worked side; the others there keep their seat-choice reason. People already approved or in a running sequence are never held out, and an overrides.csv addition at a held-out account is refused with a note. |
| + | Your additions | `overrides.csv` adds them back if rules 2 to 6 allow (strategy, owner, stops, open conversations, one live play, the gate). They come on top of the account cap. Each added person is counted with their reason. |
| 10 | Seat and account cap | Not the seat the play points to, or the account already has `per_account_cap` people. People approved earlier are seated first and count toward the cap. |
| 11 | Calendar | No start date fits before the play's end (or the event cutoff) under the daily cap. |

## Start dates

Approved rows keep their start dates and use up that day's room. New rows are placed round-robin across accounts in rank order: each business day takes at most `daily_cap` people and at most one person per account. Weekends and `daily.holidays` are skipped.

## Rows that change

- People approved earlier keep their seat and start date, and count toward the caps. A row whose sequence has already started keeps running when its account leaves the play's scope.
- What you typed in `enroll.csv` stays: `approved`, and any value in `variables` that differs from what the script wrote last time (the script keeps its own last values in `state.json`). A running sequence keeps all of its variables.
- A row approved earlier that a rule now blocks gets `drop_reason` "was approved, now blocked: ..." and shows under "Needs you" on every run. `approved` stays `yes` on that row until you clear it; daily-plan never works a row with a `drop_reason`. If the person qualifies again, the row comes back with `approved` blank and a new start date: something about the person or the account changed while they were blocked, so it needs a fresh approval.

## Rule ideas and stopping

- Each override row needs a reason. When the same reason appears on two or more rows, the report suggests making it a rule.
- `state.json` keeps one line per run day. When the last `max_quiet_runs` runs found nobody new, the report says to retire the play or change its rules.
