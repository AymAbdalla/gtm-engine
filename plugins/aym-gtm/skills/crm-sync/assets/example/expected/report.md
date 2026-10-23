# CRM sync plan 2026-10-20

**Mapping unconfirmed:** this plan uses the field mapping in gtm.json (table below). Confirm it before applying any row; a wrong mapping writes good data into the wrong field.

## Needs you

- Settle 1 conflict(s) in `conflicts.csv`: both sides changed and nothing says which is newer.
- Look at 9 item(s) in `review.csv` (ambiguous matches, unknown values, records gone from the CRM).
- Apply the 3 pilot row(s) in `to-crm.csv` first, check them in the CRM, then the rest. Check each row's current value before you change it.
- Copy `to-book.csv` into `input/` (for example `input/crm-sync.csv`), add it to `book.sources` in gtm.json, and rebuild the book with account-book.
- Append the 1 row(s) in `to-log.csv` to `log/activity.csv`.

## Field mapping (book -> CRM column)

| Book | CRM |
|---|---|
| first_name | first_name |
| last_name | last_name |
| title | title |
| email | email |
| phone | phone |
| linkedin_url | linkedin_url |
| country | country |
| status | status |

## Every export row accounted for

- CRM people rows: 9 = matched 6 + new in CRM 1 + review 2
- Planned CRM changes: 11 (3 pilot)
- Book changes: 6 row(s), reasons in `to-book-reasons.csv`
- Activity rows to add to the log: 1
- Conflicts: 1; review items: 9
- Bounces waiting for CRM confirmation: 2

## Notes

- Bounce for p03 confirmed in the CRM (first seen 2026-10-10).

Nothing was sent and no CRM was changed. A live write is a person's action, one rung at a time: plan, then copy, then live. A bare yes never skips a rung.
