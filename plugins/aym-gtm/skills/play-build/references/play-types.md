# Play types

Pick one type per play. Each type decides which accounts are in scope and how they are ranked. Everything after that (gates, seats, caps, dates) works the same way.

| Type | Accounts in scope | Ranked by | Seat |
|---|---|---|---|
| `signal` | Accounts signal-score marked `playable` in `signals/scored.csv` | Signal score, highest first | Follows the signal type (below) |
| `event` | Every account; people must live near the event (phone area code in the event's `area_codes`) | Tier points | `seat_order`; up to `event.invites_per_account` per account |
| `reactivation` | Accounts that went quiet past their own rhythm, or are tagged `lost_deal`, or have the `re-engage` strategy | Past value (`past_value` column), then tier | `seat_order` |
| `multithread` | Accounts where someone engaged (an outcome in `multithread.engaged_outcomes`) | Number of engaged people | People in lanes nobody has engaged yet; up to `multithread.per_account_cap` |
| `blitz` | The accounts listed in `play.json` `accounts` | The order you listed them | `seat_order` |

## Signal seats

`play.signal_seat_roles` maps each signal type to the roles to try, in order:

| Signal type | Seat |
|---|---|
| `new_leader` | The person the signal names, when they are in the book and pass the gate. Their `trigger_fact` says "you" ("Brightmill Manufacturing named you Chief Financial Officer"), because the line is written to them. If not, the report says so and the next role gets a plain first touch: `trigger_fact` stays blank, because the fact is about someone else, and the step is held until you write a plain first line or add the named person. |
| `leader_gap` | The most senior remaining leader. Anyone the seat text rules out ("not <name>") is never picked. |
| `hiring` | The likely manager of the open role: champion first, then decision maker. |
| `funding`, `growth` | Decision maker, then champion. |
| `topic_intent` | Decision maker. Research interest is timing only: the trigger fact is left blank and must never mention it. |

When signal-score left a `check` note on the account (the source names a different company on the same domain), the fact is not confirmed for this account. `trigger_fact` stays blank, the composed line goes into `trigger_fact_to_confirm`, and "Needs you" asks you to open the source. Copy it into `trigger_fact` only after you confirm it.

## Reactivation rhythm

For each account, the script collects outbound touch dates from `log/activity.csv` and `last_touch_date` in the book.

- Usual gap: the middle value of the gaps between touch dates. With fewer than two touches it uses `reactivation.default_interval_days`.
- Quiet: days since the last touch is at least the larger of `reactivation.min_quiet_days` and `reactivation.gap_factor` times the usual gap.
- An account nobody ever touched is prospecting, not reactivation, so it is out of scope.
- Tagged accounts skip the quiet check, but nobody touched in the last `reactivation.recent_touch_days` days is proposed.
- Rank by past value, not by how long it has been quiet. A long silence alone is not a reason to call first.
- The first touch names the gap ("it has been a while since we spoke about X") and does not pitch. Any reply, including an out-of-office, pauses the sequence. A complaint stops it.

## Event timing

The last possible start date is the event date, minus `event.finish_days_before` business days, minus the sequence length. A sequence that cannot finish before the event is not proposed. Tentative events (`status` tentative) propose nobody until they are confirmed.
