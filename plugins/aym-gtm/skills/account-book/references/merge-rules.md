# Merge and rebuild rules

## Matching people (the match ladder)

For each source row, look for the same person in this order:

1. person id
2. CRM id
3. email (ignoring case)
4. exact normalized first and last name at the same account

The first rung that finds a match wins. There is no fuzzy matching. If the name rung finds two people, the row is not merged; it is kept as its own row and logged in `conflicts.csv` for the user to settle.

## Which value wins between sources

Sources are read in the order set in `gtm.json` → `book.sources`. The default is researched list, then verified list, then the raw CRM export.

- A higher source's non-empty value wins.
- A lower source only fills blanks.
- Tags from every source are joined.
- A real person id or CRM id from any source is kept. An id is made up from the email (or name and account) only when no source has one.

## Rebuilding over an existing book

The script keeps the merged source values from the last build in `book/.built/`: what the sources said, before your edits. On a rebuild it compares the book you have now with that copy. A book value that differs from it is your edit, and it stays your edit on every later rebuild until you change it back.

| Field | Rule |
|---|---|
| Any field you changed | Your value stays. A field counts as changed when the book differs from the source value in `.built`. |
| `status`, `next_step` | Always yours after the first build. If a source changes its status since the last build, the book keeps yours and logs the difference in `conflicts.csv`. A status you set by hand is not a conflict on its own. |
| `status` with do-not-contact | A source that says `do_not_contact`, tags `opted_out` or `dnc_all`, or has a do-not-contact phrase in its notes sets `do_not_contact`. Safety beats edits. |
| `tags` | Only grow: book tags plus source tags. |
| `notes` | Only grow. `new_note` is added as a dated line, then cleared. |
| A source value went blank | The book keeps its value. Missing data is never a reason to delete. |
| Anything else | The newest source value. |
| People you added by hand | Stay, with `source` set to `manual`. Every value you typed counts as an edit. |
| People no source has any more | Stay as they are. |

Accounts follow the same rules. `strategy_override`, `pain`, `pain_status`, `next_step`, `tags` and `notes` are always yours.

`input/account-updates.csv` (from crm-sync) is read after `input/accounts.csv`: its non-blank `status`, `owner` and `relationship` values become source values, so your edits still win, with one exception. A row that sets `live_deal` (an open opportunity in the CRM) sets the account to `live_deal` whatever the book says. A row for an account that is not in the book is skipped with a warning.

## Time zone

Use the time zone from the data. If there is none, look up the phone's area code in `book.area_code_tz` and mark it `area_code_approx`. A guessed zone is not your edit: when the phone changes, the guess follows it. A time zone you type in the book wins and is marked `manual`. The script keeps that label on later rebuilds.

## CRM fixes

`fixes.csv` compares each person with `input/crm-snapshot.csv` using the same match ladder. For each field in `book.fix_fields` (default: names, title, email, phone, LinkedIn, country and status, so an opt-out that sets `do_not_contact` is sent to the CRM too), a non-empty book value that differs from the CRM becomes one fix row. After the user makes the fixes in their CRM, they export a fresh snapshot, and those rows drop off on the next rebuild.

## Made-up ids and real ids

A person who comes only from a list without ids (for example a researched list) gets a made-up id (`p-` and eight letters or digits). When a later build brings the same person from a source with a real id, the book matches them by email, then by exact name at the same account, and switches to the real id. Your edits stay, the CRM id is filled in, and `conflicts.csv` records the old and new id with the note "made-up id replaced by the id from a source". The book never keeps both.
