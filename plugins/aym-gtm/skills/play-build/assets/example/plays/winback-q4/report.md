# Play report: winback-q4 (2026-10-20)

## Needs you

- Open `enroll.csv`, read each proposed row and write `yes` (or `no`) in `approved`. Only approved rows are worked.
- variable `last_topic` is blank for p08, p15, p10: fill it in enroll.csv before the first step, or the step is held for you

## Proposed

| Rank | Person | Account | Seat | Starts |
|---|---|---|---|---|
| 1 | p08 | A04 | decision_maker | 2026-10-21 |
| 2 | p15 | A09 | decision_maker | 2026-10-21 |
| 3 | p10 | A05 | decision_maker | 2026-10-21 |

Sequence `seq-winback` runs 8 business days.

Reactivation rules: the first touch names the gap and does not pitch. Any reply, including an out-of-office, pauses the sequence. A complaint stops it.

## Notes

- 1 activity row dated after 2026-10-20 ignored as corrupt: fix the timestamp in log/activity.csv

Nothing was sent, enrolled or written to any CRM or sequencer.
