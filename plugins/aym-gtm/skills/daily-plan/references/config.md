# gtm.json: the `daily` section

Every value is an editable default, not a standard. The script uses these defaults for any key you leave out.

```json
"daily": {
  "user_timezone": "America/New_York",
  "holidays": [],
  "call_window": {"start": "08:00", "end": "21:00"},
  "preferred_window": {"start": "09:00", "end": "17:00"},
  "call_blocks": [
    {"name": "morning", "start": "09:30", "end": "11:30"},
    {"name": "afternoon", "start": "14:00", "end": "16:30"}
  ],
  "call_slot_minutes": 5,
  "min_days_between_touches": 3,
  "max_extra_cards": 20,
  "extras_per_account": 1,
  "inbound_tags": ["inbound"],
  "warm_tags": ["warm", "referral", "past_reply"],
  "weights": {"signal": 3, "seat": 2, "recency": 1, "fit": 2, "due_step": 2,
              "single_threaded": 1, "deliverability": 1},
  "recency_peak_days": [4, 14],
  "never_touched_recency": 0.8,
  "flat_gap": 0.05,
  "fact_ladder": ["inbound_untouched", "never_touched", "buying_role", "seniority", "newest"],
  "block_order": ["inbound", "warm", "linkedin_only", "volume"],
  "reply_lookback_days": 30,
  "owner": null
}
```

| Key | Meaning |
| --- | --- |
| `user_timezone` | Your time zone. Call blocks and your calendar are read in it. |
| `holidays` | Dates (`YYYY-MM-DD`) that are not business days. |
| `call_window` | Default calling window in the prospect's time zone (8am to 9pm, the US federal default; some states are stricter). |
| `preferred_window` | Hours to try first in the prospect's time zone. |
| `call_blocks` | Your calling blocks, in your time zone. |
| `call_slot_minutes` | Minutes per call slot. |
| `min_days_between_touches` | Extra touches skip anyone touched more recently. |
| `max_extra_cards`, `extras_per_account` | Caps on the extra-touch queue. |
| `inbound_tags`, `warm_tags` | Tags that put a person in the inbound or warm block. |
| `weights` | Weight of each sub-score in the queue. |
| `recency_peak_days` | Days since last touch that score highest. |
| `never_touched_recency` | Recency sub-score for someone never touched. Blank is not zero. |
| `flat_gap` | Below this spread, scores are hidden and the fact ladder orders the queue. |
| `fact_ladder` | The order used when scores are flat. An open deal is not a tie-break: live-deal accounts are never planned. |
| `block_order` | Order of the extra-touch blocks on the page. It does not decide who gets a slot. |
| `reply_lookback_days` | A reply anywhere at the account within this many days stops the account's sequences and extra touches. |
| `owner` | Your name as it appears in the account `owner` column. Blank uses `play.owner`, else `you`. Accounts owned by someone else are never planned. |

The plan also reads the shared keys `stop_statuses`, `dnc_tags`, `left_tags`, `channel_block_tags` and `send_gate.min_email_score`.
