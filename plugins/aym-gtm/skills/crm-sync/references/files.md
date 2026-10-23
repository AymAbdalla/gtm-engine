# Files and columns

## Inputs

**`input/crm-export/people.csv`** (one row per person in the CRM). Column names follow `sync.field_map` and `sync.crm_columns`; the defaults are:

`crm_id, first_name, last_name, title, email, email_status, phone, linkedin_url, country, status, account_name, account_domain, updated_at`

**`input/crm-export/accounts.csv`** (optional): `crm_id, name, domain, employees, industry, country, tier`. Account changes from the CRM are listed in the report notes for you to take into `input/accounts.csv`; account changes from the book are planned for the CRM.

**`input/crm-export/activity.csv`** (optional): `activity_id, external_id, timestamp, crm_id, channel, direction, sequence, step, outcome, notes`, plus optional `account_name` and `account_domain`. `external_id` holds the log's `activity_id` when the activity came from the log.

**`input/crm-export/bounces.csv`** (optional): `crm_id, email, timestamp, reason`.

**`input/crm-export/opportunities.csv`** (optional): `opportunity_id, account_crm_id, stage, is_closed, owner, updated_at`. Any opportunity whose `is_closed` is not true, yes, 1 or closed is open. With this file, an account with an open opportunity is planned as `live_deal`, and a book account marked `live_deal` goes back to `active` only when the file has that account's opportunities and all of them are closed. A `live_deal` account with no row in the file stays `live_deal` and is named in the report, so a partial export never reopens outbound. Without it, `live_deal` is left alone. The column names are this skill's own; map your CRM's export to them in a copy.

The accounts export may also carry `owner`, `relationship` and `status` (active, hold, live_deal or archived). Non-blank values that differ from the book go to `to-book-accounts.csv`.

**`log/activity.csv`**: the shared log, `activity_id, timestamp, person_id, account_id, channel, direction, sequence, step, play_id, angle, opener, outcome, notes, source`.

**`book/people.csv`**: from account-book. An optional `updated_at` column lets the book side win a both-changed field when its change is newer.

## Outputs (in `sync/`)

| File | Columns | Use |
|---|---|---|
| `to-crm.csv` | `row_id, action, object, record_id, field, current_value, new_value, reason, evidence, pilot` | The CRM plan. `action` is update, create or log. `pilot` is `yes` on the first rows. |
| `to-book.csv` | `person_id, account_id, crm_id`, the mapped fields, `tags` | A source file for account-book. Only changed fields are filled; blanks change nothing. New people from the CRM have a blank `person_id`. |
| `to-book-reasons.csv` | `person_id, crm_id, field, book_value, new_value, reason` | Why each book change is there. |
| `to-book-accounts.csv` | `account_id, crm_id, status, owner, relationship, reason` | Account changes from the CRM. Copy it to `input/account-updates.csv` for account-book. |
| `to-log.csv` | the log columns | CRM activity to append to `log/activity.csv`, with `source` set to `import`. |
| `conflicts.csv` | `object, record_id, person_id, field, book_value, crm_value, baseline, book_time, crm_time, reason` | Both sides changed and nothing says which is newer. |
| `review.csv` | `review_id, object, record_id, issue, detail` | Anything the sync refused to guess. |
| `cadence.csv` | `person_id, account_id, sequence, last_step, last_touch, state, reason, next_due` | Sequence state per person. |
| `report.md` | | Needs-you first, then the mapping table and the counts. |
| `state.json` | | Written whole or not at all (a temp file renamed into place). Baseline, processed activity ids, newest bounce time, export hashes and ids, waiting bounces and outcome changes, the first planned date of each create and log row, the input fingerprint and the state this run started from. Do not edit. |
| `*.stale.csv`, `report.stale.md` | | The previous plan, renamed when a run stops. Do not apply. |
| `copy/people.csv`, `copy/row-log.csv` | | Only with `--rung copy`. |

## gtm.json `sync` section

| Key | Default | Meaning |
|---|---|---|
| `fields` | first_name, last_name, title, email, phone, linkedin_url, country, status | Person fields compared. |
| `field_map` | same names | Book column to CRM column. |
| `account_fields`, `account_field_map` | name, domain, employees, industry, country, tier | Account fields compared. |
| `crm_columns` | id `crm_id`, `updated_at`, `account_domain`, `account_name`, `email_status`, activity `external_id` | Export column names. |
| `row_floor_share` | 0.8 | Stop when an export shrinks below this share of the last one. |
| `pilot_rows` | 3 | Rows in the pilot batch. |
| `next_step_business_days` | 3 | Gap to the next sequence step. |
| `create_missing` | true | Plan a create row for book people with no CRM record. |
| `carry_forward_runs` | 5 | Runs an unapplied outcome change is planned before it moves to review. |
| `channels`, `outcomes` | the shared lists | Allowed values. |
| `engaged_outcomes`, `stop_outcomes`, `status_from_outcome` | see sync rules | How outcomes change status and sequence state. |
| `bounce_crm_field`, `bounce_crm_value` | `email_status`, `invalid` | How a bounce is marked in the CRM. |
| `holidays` | `daily.holidays` if set | Dates skipped when counting business days. |
| `status_map` | "Do Not Contact", "DNC", "Unsubscribed", "Opted out" to `do_not_contact`; "On hold" to `hold`; "Meeting booked" to `booked`; "Not interested", "Wrong person", "Left company", "No longer at company" | CRM status to book status. Case, spaces, dashes and underscores are ignored; book statuses map to themselves. Anything else goes to review. |
| `status_to_crm` | empty | Book status to the spelling written in the CRM. |
