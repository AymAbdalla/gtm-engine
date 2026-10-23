# Call blocks and time zones

## Your blocks

`daily.call_blocks` lists your calling blocks in your own time zone (`daily.user_timezone`). Each block is cut into slots of `daily.call_slot_minutes`. Slots that overlap a busy time in `plan/calendar.csv` are removed.

## Your calendar

`plan/calendar.csv` has `start, end, title`. Every time needs a UTC offset, for example `2026-10-20T10:00:00-04:00`. The plan trusts the offset, not the clock digits or a zone label. A row with no offset is reported and ignored. Never book a call from a free/busy guess; read the day's events. The plan prints your time zone and its offset at the top.

## Placing calls

Calls are placed in card order, in two passes:

1. **Preferred hours:** a slot whose start and end fall inside `daily.preferred_window` in the prospect's own time zone (default 9am to 5pm).
2. **Default calling window:** any free slot inside `daily.call_window` in the prospect's time zone (default 8am to 9pm, the US federal telemarketing default). Several states are stricter (earlier evening end, later start, no Sunday calls), so set the window for the places you call. The skill does not check state rules.

Each placed card shows both times, for example `14:00 America/New_York (their time 11:00 America/Los_Angeles)`.

| What happened | Card status |
| --- | --- |
| placed | `ready` (or `no_prep`) with a slot |
| the prospect's time zone is blank or unknown | `needs_human`: check their local time before dialing |
| slots exist inside their calling window but all are taken or busy | `overflow`: carried to tomorrow |
| none of today's blocks fall inside 8am to 9pm their time | `skipped`: not missed. A sequence call step skips and the sequence moves on |

## Time zone names

Use IANA names from the book's `timezone` column, such as `America/Chicago` or `Pacific/Honolulu`. account-book fills them from the data, your edits, or the phone's area code (marked approximate). On Python 3.8, which has no time zone database, the script uses a built-in table of North American zones with the US and Canada daylight saving rule.
