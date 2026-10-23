# Book schema

The book is two CSV files under `book/`. Every input column is kept. The scripts add the columns below.

## Prospect book: `book/people.csv` (one row per person)

Input columns, from the shared GTM layout:

`person_id, account_id, first_name, last_name, title, email, email_status, email_score, phone, linkedin_url, country, timezone, status, last_touch_date, sequence, tags, notes, crm_id, source`

Added by `build_book.py`:

| Column | Meaning |
|---|---|
| `persona` | First persona in `gtm.json` whose title pattern matches. Blank when none match. |
| `lane` | The persona's lane, such as finance, tech or ops. |
| `role` | The persona's role in the buying group: decision_maker, champion, influencer or technical_gatekeeper. |
| `send_ok` | `yes` when the person passes the send gate, else `no`. The gate covers the person, their title and their account's strategy, not only the email. |
| `send_block_reason` | Every reason the gate blocked them, joined with `; `. |
| `followup_ok`, `followup_block_reason` | `yes` when the person may get the next step of the sequence they are already in: the same checks as `send_ok` except the sequence rule. `no` with reasons otherwise, including "not in a sequence". |
| `call_ok`, `call_block_reason` | `yes` or `no` for calls: a phone, a buyer at an account where outbound is allowed, no stop status, no do-not-contact tag or note, no do-not-call or failed-phone tag. |
| `linkedin_ok`, `linkedin_block_reason` | `yes` or `no` for LinkedIn touches (connect notes and messages): a LinkedIn URL, a buyer at an account where outbound is allowed, no stop status, no do-not-contact or left tag or note, no `channel_block_tags.linkedin` tag. |
| `timezone_source` | `data`, `manual` (you typed it), `area_code_approx` (from the phone), or `unknown`. |
| `next_step` | Yours. The script never changes it. |
| `new_note` | Type today's note here. The next rebuild adds it to `notes` as `YYYY-MM-DD: text` and clears this cell. |

### Person status

| Status | Meaning |
|---|---|
| active | Can be worked. |
| nurture | Keep warm, no active sequence. |
| hold | Paused on purpose. |
| booked | A meeting is booked. |
| not_interested | Said no. |
| wrong_person | Not the right contact. |
| left | No longer at the account. |
| do_not_contact | Never contact on any channel. |
| archived | Out of the book's working set. |

Only `active` and `nurture` pass the default send gate.

## Account book: `book/accounts.csv` (one row per account)

Input columns:

`account_id, name, domain, other_domains, employees, industry, country, tier, relationship, status, owner, crm_id, notes`

Added by `build_book.py`:

| Column | Meaning |
|---|---|
| `people_count` | Everyone in the book at this account. |
| `buying_group_count` | People with a persona. |
| `send_ok_count` | Buying-group people who pass the send gate. |
| `readiness` | `ready` (at least `book.ready_min` send-ready buyers), `enrich` (buyers exist but too few pass), `prospect` (no buyers yet). |
| `lanes_covered`, `lanes_missing` | Persona lanes with and without a contact. |
| `strategy`, `strategy_reason` | The first strategy rule that matched, with why. |
| `strategy_override` | Yours. Set it and the strategy sticks. |
| `pain`, `pain_status` | Your pain line and `hypothesis` or `heard`. |
| `next_step`, `tags` | Yours. Tag `lost_deal` to send an account to re-engage. |

## Other files

| File | What it holds |
|---|---|
| `book/fixes.csv` | `person_id, crm_id, field, crm_value, book_value`: book values that differ from `input/crm-snapshot.csv`. These are the changes to make in the CRM. |
| `book/conflicts.csv` | Matches the script refused to guess, and status changes from a source that the book did not apply. |
| `book/accounts.md` | One table: strategy, reason, readiness, send-ready count, lanes missing. |
| `book/top.json`, `book/top-report.md` | The sticky top list and its report (from `rank_accounts.py`). |
| `book/export.csv`, `book/export-left-out.csv` | Send-ready people at chosen accounts, and everyone left out with the reason. |
| `book/.built/` | What the script last wrote. It is how the next rebuild tells your edits from source changes. Do not edit it. |
