# Play report: signal-oct (2026-10-20)

## Needs you

- Open `enroll.csv`, read each proposed row and write `yes` (or `no`) in `approved`. Only approved rows are worked.
- Ruth Okoye (p19): the only signal is research interest. Use it for timing only and never mention it. Put a sourced, dated fact in trigger_fact only if you find one; otherwise the step is held.
- Ruth Okoye (p19): reply by hand first: the override reason suggests a live conversation ("AP lead asked for a demo at a webinar", matched "demo"). trigger_fact is left blank. Answer them yourself before any sequence step, then decide if this play still fits.
- Elena Marsh (p17): the only signal is research interest. Use it for timing only and never mention it. Put a sourced, dated fact in trigger_fact only if you find one; otherwise the step is held.
- variable `trigger_fact` is blank for p19, p17: fill it in enroll.csv before the first step, or the step is held for you
- open each source link before the first touch (p01, p04 quote a dated fact). If the page is gone or says something else, clear trigger_fact.

## Proposed

| Rank | Person | Account | Seat | Starts |
|---|---|---|---|---|
| 1 | p04 | A02 | decision_maker (signal seat: Dana Whitfield, Chief Financial Officer (the named new leader)) | 2026-10-21 |
| 2 | p01 | A01 | decision_maker (signal seat: the likely manager of the open role) | 2026-10-21 |
| 3 | p19 | A10 | added by you: AP lead asked for a demo at a webinar | 2026-10-22 |
| 4 | p17 | A10 | decision_maker (signal seat: decision maker) | 2026-10-23 |

Sequence `seq-trigger-finance` runs 6 business days.
Last possible start: 2026-11-13.

## Notes

- 1 activity row dated after 2026-10-20 ignored as corrupt: fix the timestamp in log/activity.csv

Nothing was sent, enrolled or written to any CRM or sequencer.
