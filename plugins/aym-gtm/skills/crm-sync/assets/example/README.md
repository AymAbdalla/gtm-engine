# crm-sync example

A made-up Ledgerline workspace. Every company, person, address and phone number is invented (`.example` domains, 555 numbers).

`sync/state.json` is the last run's state (2026-10-15). `expected/` holds what one run on 2026-10-20 writes.

Run it on a copy, so the example stays as it is:

```
cp -r <skill-dir>/assets/example /tmp/gtm-example
python3 <skill-dir>/scripts/sync_crm.py --workspace /tmp/gtm-example --today 2026-10-20
```

## What the run should show

| Case | Where | Result |
|---|---|---|
| Book changed the title since the last sync (Dana, C-P01) | `to-crm.csv` | update title to "Chief Financial Officer" |
| CRM changed the phone since the last sync (Marcus, C-P02) | `to-book.csv` | new phone for p02 |
| Both changed the title, both have times (Priya, C-P03) | `to-crm.csv` | the book change is newer and wins |
| Both changed the phone, the CRM time is after today (Hollis, C-P04) | `conflicts.csv`, `review.csv` | the future time is ignored, nobody wins |
| CRM email is blank (Tessa, C-P05) | `to-crm.csv` | a blank never clears the book; fill the CRM |
| Missing from the new export (Grace, C-P06) | `review.csv` | "closed or removed", nothing deleted |
| In the book, not the CRM (Sam, p07) | `to-crm.csv` | one create row that also carries his opt-out |
| Two book people with the same name at one account (Alex Rivera) | `review.csv` | ambiguous match; neither is created |
| New in the CRM at a book account (Mei, C-P11) | `to-book.csv` | a full row to bring into the book |
| New in the CRM at an unknown account (Rafael, C-P12) | `review.csv` | not brought in |
| Bounce in the log (Owen, a005) and in the CRM export (Hollis) | `to-book.csv`, `to-crm.csv` | tag `bounced`, mark the CRM address invalid, wait for confirmation |
| Earlier bounce now shown as invalid in the CRM (Priya) | `report.md` notes, `to-book.csv` | confirmed, dropped from the waiting list; the book gets the `bounced` tag it still lacks |
| Opt-out logged (Sam, a008) | `to-book.csv` | status `do_not_contact`, tag `opted_out` |
| Unknown outcome values (`accepted`, `left_voicemail`) | `review.csv` | not imported; new values are never created |
| A log time after today (a007) | `review.csv` | ignored |
| CRM dialer call not in the log (CA-10) | `to-log.csv` | a row to append to `log/activity.csv` |
| Reply from Marcus at Northpine | `cadence.csv` | Marcus replied; Dana's sequence stops for the account |
