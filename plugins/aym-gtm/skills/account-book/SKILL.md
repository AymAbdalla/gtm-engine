---
name: account-book
description: Build and rebuild the prospect book (one row per person) and the account book (one row per account) from your source lists, keeping your own edits every time. Adds a send gate per channel, buying-group lanes, account readiness, one strategy per account, CRM fixes and a sticky top-accounts list. Use to build or refresh the book, merge lists into one record per person, see which accounts are ready, or pick top accounts. Not for cleaning lists (data-quality), scoring signals (signal-score), messages (outreach-draft) or the ICP (icp-define).
---

# Account book

Turn several messy lists into one book you can work from every day. Each person appears once. Each account gets a readiness level and one strategy with a reason. Your edits survive every rebuild. The skill writes files only. It never sends a message, enrolls anyone or writes to a CRM.

## If the script cannot run

This skill's results come from `scripts/build_book.py` and `scripts/rank_accounts.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write the book files (`book/people.csv`, `book/accounts.csv`, `fixes.csv`, `conflicts.csv`, `accounts.md`, `top.json`) or `book/.built/` by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/build_book.py --workspace <workspace> --today YYYY-MM-DD`.

## Inputs

All paths sit in the GTM workspace (default `./gtm`). See [book schema](references/schema.md) for every column. In the commands below, `<skill-dir>` is this skill's folder and `<workspace>` is the path to the user's GTM workspace.

- `gtm.json`: personas, not-buyer titles, stop statuses and do-not-contact tags, the email send gate, the `icp` section (read through the shared fit rule in `scripts/gtm_fit.py`), and the `book` and `ranking` sections. Missing sections fall back to defaults in the scripts. Every number is an editable default, not a standard.
- `input/accounts.csv`: one row per account.
- Person sources, in precedence order from `book.sources` (default `input/researched.csv`, `input/verified.csv`, `input/people.csv`). A file in `book.required_sources` (default `input/people.csv`) must exist or the build stops and writes nothing; any other listed file that is missing is skipped with a warning.
- The book is the full record of everyone in your sources, including people data-quality quarantined. Its gates still block them (do-not-contact, opt-outs, not-buyer titles, excluded or held accounts), each with a reason. To keep a person out of the book entirely, remove them from the source files. To build the book from data-quality's work list instead, put `clean/ready.csv` first in `book.sources`. To use data-quality's verify results, copy `verified/safe.csv` to `input/verified.csv`, which is already in the default sources.
- Optional `input/crm-snapshot.csv`: people as your CRM holds them today.
- Optional `input/account-updates.csv`: account status, owner and relationship from your CRM (crm-sync writes it as `sync/to-book-accounts.csv`). An open deal there sets the account to `live_deal`, even over your own edit.
- Optional `signals/scored.csv` from signal-score.

When the user has no workspace yet, ask for their account and people files, or offer the made-up example in [assets/example](assets/example/README.md). Customer or employer data stays where the user is allowed to keep it. Do not copy it into this skill or any public place.

## Steps

1. **Check the inputs.** Confirm the workspace path, which source files exist and their order. Read [merge rules](references/merge-rules.md) if the user asks how conflicts resolve.
2. **Build the book.** Run:
   `python3 <skill-dir>/scripts/build_book.py --workspace <workspace> --today YYYY-MM-DD`
   It writes `book/people.csv`, `book/accounts.csv`, `book/fixes.csv`, `book/conflicts.csv`, `book/accounts.md`, and `book/.built/` (the merged source values from the last build, used to spot your edits; do not edit these).
3. **Rank top accounts** when the user wants a focus list:
   `python3 <skill-dir>/scripts/rank_accounts.py --workspace <workspace> --today YYYY-MM-DD`
   The first run freezes the list in `book/top.json`. Later runs keep it and only report challengers. See [strategy and ranking](references/strategy.md).
4. **Export a send list** when the user names accounts:
   `python3 <skill-dir>/scripts/build_book.py --workspace <workspace> --today YYYY-MM-DD --export A01,A02`
   `book/export.csv` holds people whose `send_ok` is `yes`. An unknown account id stops the run with an error. `book/export-left-out.csv` lists everyone else at those accounts with the reason.
5. **Review with the user.** Walk through `accounts.md`, `conflicts.csv` and `fixes.csv`. Point out accounts on hold or excluded, lanes with no contact, and people blocked by the gate.

## Rules that matter most

- **One record per person.** Match by person id, then CRM id, then email, then the exact name at the same account. Never guess with fuzzy matching. A name that fits two people goes to `conflicts.csv`.
- **Your edits win.** Status, tags, notes, next step and any field you changed stay as you left them. People you added by hand stay. Tags and notes only grow. Type a note in `new_note`; the next rebuild adds it to `notes` with the date.
- **Do-not-contact always wins.** A source that says do_not_contact, tags opted_out or dnc_all, or has a do-not-contact phrase in its notes sets the status to do_not_contact, whatever you typed.
- **Never delete because data went missing.** A blank source value keeps the book value.
- **Send gate before any export.** `send_ok` is `yes` only for a buyer at an account where outbound is allowed, with a safe email. Accounts outside the ICP (the shared fit rule in `scripts/gtm_fit.py`: size floor and ceiling, countries, industries, tech, excluded relationships), accounts whose fit is unknown because a field is blank, and held and live-deal accounts stay out, and so do not-buyer titles. The same person and account checks set `call_ok` and `linkedin_ok`, so a person blocked for who they are or where they work is blocked on every channel. See [send gate](references/send-gate.md).
- **A live deal beats everything but a hold.** An account with an open deal gets strategy `live`, even if someone there replied before, and nobody there is contacted. The deal owner leads.
- **Ready means a decision maker can be reached.** `ready` needs at least `book.ready_min` send-ready buyers, including the roles in `book.ready_requires_roles` (default a decision maker).
- **Pain is a hypothesis until someone hears it on a call.** Change `pain_status` to `heard` only then.
- **Facts need a source.** Any claim added to `pain` or `notes` about an account names where it came from and when.

## Boundaries

The skill does not clean raw lists, verify emails, call any vendor, write to a CRM or sequencer, or send anything. `fixes.csv` lists changes for the user to make in their CRM; after they make them, they refresh `crm-snapshot.csv`.

## Report

Tell the user:
- the files written, with paths
- counts: people, accounts, send-ready people, fixes, conflicts, people with no CRM id, people added by hand
- accounts by strategy and readiness, and lanes with no contact
- who was left out of an export and why
- what needs them: resolve conflicts, make the CRM fixes, confirm any challenger before changing the top list
- what the skill did not do: send, enroll, or write to any system
