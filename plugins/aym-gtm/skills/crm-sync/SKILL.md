---
name: crm-sync
description: Keep the prospect book and the CRM in step through files. Compares the book and activity log with a fresh CRM export, open deals included, and plans CRM changes, book and account updates, log rows, conflicts and a review list. Newer change wins, a blank never wipes a value, a short export stops the run. Use for "sync with the CRM", "what changed in the CRM" or "handle the bounces". Not for cleaning lists, the book or reports. The script never writes to a CRM; a person applies the plan.
---

# CRM sync

The book is where the work happens. The CRM is where the company keeps the record. This skill finds every difference between them and writes a plan for each side. It never calls a CRM and never changes the book; a person applies the plan, one rung at a time.

## If the script cannot run

This skill's results come from `scripts/sync_crm.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write any `sync/` plan file or `sync/state.json` by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/sync_crm.py --workspace <workspace> --today YYYY-MM-DD`.

## Inputs

All paths sit in the user's GTM workspace (`<workspace>`, default `./gtm`). `<skill-dir>` is this skill's folder. Column details are in [files and columns](references/files.md).

- `book/people.csv` and `book/accounts.csv` from account-book.
- A fresh CRM export in `input/crm-export/`: `people.csv` (required), and optional `accounts.csv`, `activity.csv`, `bounces.csv` and `opportunities.csv` (open deals; see [files](references/files.md)).
- `log/activity.csv`, the shared activity log.
- `sync/state.json` from the last run, if there was one.
- `gtm.json`: the `sync` section (field mapping, row floor, pilot size and more) plus the shared stop statuses and tags. Every number is an editable default.

When the user has no workspace yet, offer the made-up example in [assets/example](assets/example/README.md). Customer or employer data stays where the user is allowed to keep it.

## Steps

1. **Show the field mapping.** Read `sync.field_map` and show it as a table: which book column goes to which CRM column, and ask the user to confirm it. A wrong mapping writes good data into the wrong field. Once they confirm, add `--mapping-confirmed` to the run. With nobody there to confirm, run without it: the plan is only a file, and its report opens with "Mapping unconfirmed" so nobody applies it before checking.
2. **Plan.** Run:
   `python3 <skill-dir>/scripts/sync_crm.py --workspace <workspace> --today YYYY-MM-DD`
   If an export is much smaller than the last one, the run stops and changes nothing. Ask the user to export again.
3. **Walk through `sync/report.md` with the user.** It opens with what needs them. Then `conflicts.csv` (both sides changed and nothing says which is newer) and `review.csv` (ambiguous matches, unknown values, records gone from the CRM). Never guess on either.
4. **Optional copy rung.** To see the result before touching the CRM:
   `python3 <skill-dir>/scripts/sync_crm.py --workspace <workspace> --today YYYY-MM-DD --rung copy`
   It applies the planned person updates to a copy of the export in `sync/copy/` and writes a row log (applied, skipped, drift, failed).
5. **Hand over the plan.** This script never writes to a CRM. The user, or a tool the user runs and approves row by row, applies `to-crm.csv`: the pilot rows first, checked in the CRM, then the rest. Each row names one record and one field, and shows the value the CRM held when the plan was made; if the CRM shows something else now, skip that row and rerun the sync. `to-book.csv` goes into `input/` as a source for account-book. `to-book-accounts.csv` (account status, owner and relationship, and `live_deal` for any account with an open opportunity) is copied to `input/account-updates.csv`; account-book then stops all outbound at accounts with an open deal. `to-log.csv` gets appended to `log/activity.csv`.

The rules behind each step are in [sync rules](references/sync-rules.md).

## Rules that matter most

- **Never fuzzy.** Match by CRM id, then email, then the exact name at the same account. Two possible matches go to review.
- **Newer change wins.** The last sync's agreed values tell which side changed. When both changed, the newer time wins. A missing time, or a time after today, means no winner: it is a conflict.
- **A blank is not a value.** A blank never clears the other side.
- **Nothing dropped silently.** Every export row ends as matched, new, or review. A record missing from the new export is "closed or removed, outcome not in the export", never assumed won or deleted.
- **Do-not-contact always wins** on either side.
- **Unknown values are never created.** An outcome, channel or CRM status that is not on its list (`sync.status_map` for statuses) goes to review.
- **CRM outcomes count too.** An opt-out or other stop logged in the CRM becomes a status change in the same run. Activity is tracked by id, so nothing is skipped or counted twice.
- **Same inputs, same plan.** A rerun on unchanged inputs writes the same plan and does not move the state on; the copy rung never saves state. A stopped run renames the old plan files to `*.stale.csv`.
- **Rows that disagree go to review.** A log or CRM activity row whose person is at another account in the book is never planned.
- **Carry forward until confirmed.** Bounces, opt-outs and other outcome changes stay in the plan until the other side shows them. A create or a logged activity that comes back is marked: search the CRM before applying it again, because a second copy is a duplicate.

## Report

Tell the user: the files written under `sync/`, the accounting line (export rows = matched + new + review), how many CRM changes are planned and which are the pilot, conflicts and review items with the top reasons, bounces waiting for confirmation, and anything the run refused (row floor, live rung). Say plainly that nothing was sent and no CRM was changed.
