# Sync rules

## Matching

Each CRM export row is matched to one book person, in this order:

1. CRM id (`crm_id` in the book, the id column in the export)
2. email, ignoring case
3. the exact first and last name at the same account (the export's account domain or name matches the book account's domain, other domains or name)

The first rung that finds exactly one person wins. Two people on any rung go to `review.csv`. Book people named in an ambiguous match are not created in the CRM either; that waits until a person settles who is who. There is no fuzzy matching anywhere.

## Which side changed

`sync/state.json` keeps the values both sides agreed on at the last sync (the baseline). For each mapped field:

| Book vs CRM | Result |
|---|---|
| Same | Agreed. The baseline moves to this value. |
| Book is `do_not_contact` | Goes to the CRM. Safety wins. |
| CRM is `do_not_contact` | Comes into the book. Safety wins. |
| CRM blank, book has a value | Fill the CRM. A blank never clears the book. |
| Book blank, CRM has a value | Fill the book. |
| Only the book differs from the baseline | Goes to the CRM. |
| Only the CRM differs from the baseline | Comes into the book. |
| Both differ, both have times | The newer time wins, with both times as evidence. |
| Both differ, a time is missing, unreadable or after today | Conflict. Nobody wins. |

Status values are mapped before they are compared. `sync.status_map` turns a CRM spelling into a book status, ignoring case, spaces, dashes and underscores ("Do Not Contact" and "do-not-contact" both mean `do_not_contact`). Every book status maps to itself. A CRM status that is not on the map goes to `review.csv` as "unknown CRM status" and never reaches the book. `sync.status_to_crm` gives the spelling to write back; blank means the same word.

The baseline only moves when both sides agree. A change the user has not applied yet keeps showing in the plan.

Times come from an optional `updated_at` column on each side. A time must carry its UTC offset to compare fairly; a date alone counts as midnight UTC. A time after today is treated as blank and listed in `review.csv`.

## Row floors and stopped runs

A short export looks exactly like mass deletion. If `people.csv`, `accounts.csv` or `opportunities.csv` has fewer rows than `sync.row_floor_share` (default 0.8) of the last export, the run stops, writes only `report.md`, and leaves the state alone. Export again.

When a run stops (a row floor, or a missing book or export), the last run's plan files are renamed to `*.stale.csv` (and `report.stale.md`) so nobody applies an old plan beside a stopped report.

## Same inputs, same plan

The state keeps one fingerprint of every input the run read (the export files, the log, the book and `gtm.json`) and the state the run started from. Running again on the same inputs starts from that same state, so it writes the same plan, and the state does not move on. The copy rung never saves the state either: run the plan rung to record a sync.

## Activity is tracked by id

Each log row and each CRM activity row has its outcome turned into book changes once, tracked by its id in the state (`processed_activity`). A CRM row keeps the id `crm-<activity_id>`, so when the user appends it to the log it is not counted again. The state also keeps the newest time it saw (for bounces), a content hash and row count for each export file, so the report can say which files did not change.

A log row or CRM activity row whose person is at a different account in the book goes to review as "person and account disagree". It is not planned for the CRM and not brought into the log. The person is still clear from their id, so a stop outcome on that row (an opt-out, not interested, wrong person, left, or a bounce) is still applied to the person in the same run. Only the activity row waits for the fix.

Rows that wait for a person do not depend on time. Log rows the CRM does not have yet, CRM activity the log does not have yet, unconfirmed bounces and unapplied outcome changes come back on every run until the other side shows them. An outcome change planned more than `sync.carry_forward_runs` times without being applied moves to review. Field updates are safe to apply twice; a create or a logged activity is not. When a create or log row was planned on an earlier run and the export still does not show it, its reason says so and the report asks you to search the CRM before applying it again. The state remembers the first planned date (`planned_writes`).

## Account status, owner and open deals

The CRM is the record for three account fields: `status`, `owner` and `relationship`. Non-blank CRM values that differ from the book go to `to-book-accounts.csv`; a blank never clears the book. With `opportunities.csv`, an account with an open opportunity is set to `live_deal` (the deal owner leads), and a book account at `live_deal` goes back to `active` only when the export has that account's opportunities and all are closed. One with no row in the export stays `live_deal` and the report names it ("Live deal kept at ..."): a partial export must never reopen outbound. Copy the file to `input/account-updates.csv` and rebuild the book: account-book applies these as source values, except that an open deal sets `live_deal` even over a hand edit. Nothing is planned for the CRM from these fields.

## Outcomes from the log and the CRM

Outcomes count the same whether they were logged in `log/activity.csv` or in the CRM's activity export. An opt-out logged in the CRM becomes `do_not_contact` in the book plan in the same run. The CRM status update is planned only when the CRM export does not already show it.

| Outcome | Book | CRM |
|---|---|---|
| booked, not_interested, wrong_person, left | status set to the same name | status update |
| opt_out | status `do_not_contact` and the first `dnc_tags` tag | status update |
| left | also the first `left_tags` tag | |
| bounced | tag `bounced`, address kept | `sync.bounce_crm_field` set to `sync.bounce_crm_value` |

A later outcome for the same person replaces an earlier one. account-book takes do-not-contact from a source file; other status changes are listed for the user to set in the book.

## Sequence state

`cadence.csv` gives each person and sequence in the log one state:

- `replied`: an engaged outcome (replied, interested, not_now, booked).
- `stopped`: a stop outcome (not_interested, opt_out, wrong_person, left, bounced), or a reply from anyone else at the same account.
- `active`: next step due `sync.next_step_business_days` business days after the last touch, skipping weekends and holidays.

## The bounce loop

1. A bounce arrives from `bounces.csv` or a `bounced` row in the log.
2. The book gets the tag `bounced` and keeps the address. The send gate then drops the person.
3. The CRM plan marks the address invalid.
4. On the next run, if the export shows the address as invalid, the bounce is confirmed and leaves the waiting list. Otherwise it is planned again.
5. Whenever the export shows an address as invalid (`sync.bounce_crm_field` set to `sync.bounce_crm_value`) and the book person lacks the `bounced` tag, `to-book.csv` plans the tag. This holds whether or not the bounce was waiting, so confirming a bounce never drops the tag, and a bounce first recorded in the CRM reaches the book too. The tag is planned once per person per run.

## Write rungs

| Rung | Who | What happens |
|---|---|---|
| plan | this script (default) | Plan files only. |
| copy | this script, `--rung copy` | Planned person updates applied to a copy of the export, with a row log. |
| live | a person, or a tool the person runs and approves | The person applies `to-crm.csv` in their CRM. This script never does. |

The script refuses `--rung live`. A bare "yes" never moves up a rung: each rung needs its own clear go-ahead. Every planned row names one record and one field; there are no bulk writes without a record id. The first `sync.pilot_rows` rows (default 3) are the pilot: apply those, check them in the CRM, then do the rest. When applying, check the CRM still shows `current_value`; if not, skip the row and rerun the sync. Keep going past a failed row and note it.

## Unknown values

Channels and outcomes must be on `sync.channels` and `sync.outcomes`. Anything else goes to review. The sync never adds a new value to a list.
