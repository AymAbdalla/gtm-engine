# play.json

One file per play at `plays/<play_id>/play.json`. Keys you leave out fall back to the `play` section of `gtm.json`, then to the script's defaults.

```json
{
  "id": "signal-oct",
  "type": "signal",
  "name": "October signal play",
  "trigger": "accounts signal-score marked playable",
  "sequence": "seq-trigger-finance",
  "start": "2026-10-21",
  "end": "2026-11-13",
  "channel": "email",
  "daily_cap": 2,
  "per_account_cap": 1,
  "personas": [],
  "stop_rules": ["any reply", "meeting booked", "not interested",
                 "reply from anyone at the account stops the account"]
}
```

| Key | Meaning |
|---|---|
| `id` | Lowercase letters, numbers and dashes. It is also the folder name. |
| required | `id`, `type`, `sequence`, `start`, `channel` and `daily_cap`. A play missing any of them is refused and nothing is written: ask the user. |
| `type` | `signal`, `event`, `reactivation`, `multithread` or `blitz`. |
| `sequence` | A sequence id from `outreach/sequences.json`. Its length sets event cutoffs; its variables become columns to fill. |
| `start`, `end` | First and last possible start dates. `end` is optional. |
| `channel` | `email` uses `send_ok`, `call` uses `call_ok`, `any` uses either. |
| `daily_cap`, `per_account_cap`, `recent_touch_days`, `owner`, `seat_order`, `max_quiet_runs`, `conversation_days` | Override the `gtm.json` defaults for this play. `daily_cap` is required in play.json itself. |
| `holdout_share` | 0 to 0.5, default 0. That share of eligible accounts stays untouched for comparison (see eligibility rule 9b). |
| `personas` | Persona ids allowed in. Empty means any buyer. |
| `accounts` | Blitz only: account ids in the order to work them. |
| `event` | Event only: `{"event_id": "E1", "invites_per_account": 2, "finish_days_before": 2, "file": "input/events.csv"}`. |
| `reactivation` | Optional overrides: `min_quiet_days`, `gap_factor`, `default_interval_days`, `account_tags`, `recent_touch_days`. |
| `multithread` | Optional overrides: `engaged_outcomes`, `per_account_cap`. |
| `stop_rules` | Plain words for whoever runs the sequence. daily-plan applies the stop rules. |

## Events CSV

`event_id, name, date, city, area_codes, topic, personas, status`

`area_codes` and `personas` are semicolon lists. `status` is `confirmed` or `tentative`.

## enroll.csv

`play_id, person_id, account_id, seat, sequence, sequence_start, variables, rank, approved, drop_reason`

- `variables` is a JSON object: what the play knows (first name, company, the signal's fact and source, event details, the quiet gap) plus every variable the sequence declares. For a signal play, `trigger_fact` is written to read after "I saw": the account name, then the source's fact with its first letter lowered ("Northpine Logistics posted an opening for an Accounts Payable Manager"). A fact that already starts with the account name is kept as it is. `source_url` and `source_date` travel with it so the person can open the source before the first touch. Research-interest signals leave `trigger_fact` blank, because they are never quoted. When signal-score's `check` note says the source may be about another company, `trigger_fact` is blank and `trigger_fact_to_confirm` holds the line to copy after you open the source. When the seat is the new leader the signal names, the line is written to them in the second person ("Brightmill Manufacturing named you Chief Financial Officer"), never with their own name. When the named new leader is not in the book, the fallback seat gets a plain first touch with `trigger_fact` blank. A person you added in `overrides.csv` for a reason that suggests a live conversation (see `override_conversation_words` below) is still proposed, but `trigger_fact` is blank and "Needs you" says to reply by hand first. Blank values are listed under "Needs you"; daily-plan holds any step with a blank variable for a person.
- `approved` is yours: `yes` or `no`. Reruns keep it, and keep any variable value you typed.

## overrides.csv

`person_id, action, reason, date`. `action` is `add` or `remove`. When an add's reason contains a word from `play.override_conversation_words` in `gtm.json` (default demo, asked, requested, replied, reply, meeting, call back, intro; a word also matches its other forms, so "asked" finds "asks"), the person is still proposed, `trigger_fact` is left blank and "Needs you" says: reply by hand first, the override reason suggests a live conversation. A cold first line would ignore what they already said to you.

## Settings in gtm.json `play`

Besides the caps above: `stop_outcomes` (log outcomes that stop a person on every channel; default opt_out, not_interested, wrong_person, left), `email_stop_outcomes` (stop on email plays; default bounced), `conversation_outcomes` (default replied, interested, not_now, booked), `conversation_days` (default 30) and `override_conversation_words` (see overrides.csv above). Every value is an editable default.
