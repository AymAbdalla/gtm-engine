---
name: data-quality
description: Clean a prospect list, verify it before outreach, or audit a CRM export and write fix tickets. Sorts every person into ready, later, review, enrich or quarantine with a reason; holds anything a verification file does not clearly clear; scores CRM health and orders the fixes. Writes files only. Use for "clean this list", "who can I actually call", "verify these before I send", "audit my CRM", "find bad data" or "write the data fix tickets". Not for the ICP (icp-define), the book (account-book), signals (signal-score) or messages (outreach-draft).
---

# Data quality

Turn messy GTM data into lists you can trust and fixes you can submit. Three modes share one rule: **nothing is dropped silently and nothing is guessed.** Every row ends in a file with a reason. Do-not-contact always wins.

## If the script cannot run

This skill's results come from `scripts/clean_list.py`, `scripts/verify_split.py` and `scripts/audit_crm.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write any `clean/`, `verified/` or audit output (including `fixes.csv`) by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Give the user the command to run when they can: `python3 <skill-dir>/scripts/clean_list.py --workspace <workspace> --today YYYY-MM-DD`.

## Ground rules

- Work on files. Never send a message, enroll anyone, call a vendor or write to a CRM. The user submits fixes.
- Use only data the user is allowed to keep in this workspace. Customer and employer data stays in its own environment.
- Every threshold is an editable default in `gtm.json`, not a standard. Say so when you report one.
- A vendor with no record of a person is not proof they left.
- Matching goes ID, then email, then exact normalized name at the same account. Never fuzzy. A tie goes to review, and so do two people at one account with the same phone and last name.
- ICP fit comes from the shared fit rule (`scripts/gtm_fit.py`, the same file icp-define, account-book and signal-score use). A known reason to be out quarantines the person; a blank account field (country, industry, headcount, tech) sends them to `enrich.csv` as "account fit unknown".
- Account duplicates are never merged here. The audit lists them in the review queue for a person.
- `ready` means the data is usable. It is not permission to email; account-book's send gate decides that. The account book keeps the full record and its gates block quarantined people again; nothing is copied across automatically.
- One list of stop statuses (`stop_statuses`), opt-out tags (`dnc_tags`), left tags (`left_tags`), channel blocks (`channel_block_tags`) and personal email domains (`freemail_domains`) in `gtm.json` drives every mode.

## Pick the mode

| The user wants | Mode | Script | Detail |
|---|---|---|---|
| A usable list from a raw export | Clean a list | `scripts/clean_list.py` | [clean-list.md](references/clean-list.md) |
| To know who is safe to contact on one channel | Verify, then split | `scripts/verify_split.py` | [verify-split.md](references/verify-split.md) |
| A health score and fix plan for a CRM | Audit a CRM | `scripts/audit_crm.py audit` | [audit-crm.md](references/audit-crm.md) |
| To submit fixes safely | Recheck tickets | `scripts/audit_crm.py recheck` | [fix-tickets.md](references/fix-tickets.md) |

If the request is unclear, ask which one. A full cleanup usually runs audit, then clean, then verify.

## Inputs

A GTM workspace (default `./gtm`) with `gtm.json`, `input/accounts.csv` and `input/people.csv` in the shared aym-gtm columns. Clean mode needs `personas` in `gtm.json`; if they are missing, run icp-define first or ask the user for their buyer titles. Verify mode also needs a verification CSV the user exported from their vendor (`person_id, email, channel, verdict, score`). Audit mode can take a `sequences.csv` (`person_id, sequence, step, due_date, status`); without it, the sequence check is reported as not run.

If the columns differ, map them to the shared names in a copy. Never edit the user's original export.

## Steps

1. Confirm the mode, the workspace path, the date to treat as today and where outputs go (default `clean/`). Outputs never overwrite inputs; the scripts refuse.
2. Run the script for the mode. `<skill-dir>` is this skill's folder; `<ws>` is the user's workspace. Use absolute paths so it works from any folder:
   ```
   python3 <skill-dir>/scripts/clean_list.py --workspace <ws> --today 2026-10-20
   python3 <skill-dir>/scripts/verify_split.py --list <ws>/clean/ready.csv --verification <ws>/input/verification.csv --channel email --config <ws>/gtm.json --out <ws>/verified
   python3 <skill-dir>/scripts/audit_crm.py audit --workspace <ws> --sequences <ws>/input/sequences.csv --today 2026-10-20
   ```
   To try it on the bundled made-up data, use `--workspace <skill-dir>/assets/example` with an `--out` folder outside the skill, such as a temp folder.
3. Read the outputs before reporting. Spot-check five rows from each bucket against the input: does the reason match the row? If a rule misfires for this user's market (titles, phone formats, size bands), show the `gtm.json` change you propose and why, make it only after the user agrees, then rerun and say what changed.
4. For audit mode, walk the fix plan in its order: stops, suppression fields, exclusions, bounce triage, sequences, records, enrichment last. Merges, unclear domains and double enrollments stay in the review queue for a person.
5. Before the user submits any ticket, have them export again and run `recheck`. Only `fixes-ready.csv` goes in. Anything that drifted is re-planned, not forced.

## Report

- Files written, with paths.
- Counts per bucket (clean), safe vs held with the top held reasons (verify), or, for an audit, the scope (what was read, checked and skipped), the verdict in its "within scope" wording, the health score and grade, and ticket counts per step (audit). Never call the CRM clean or passing.
- What needs the user: review queue items, people to enrich, tickets to recheck and submit.
- What this skill did not do: send, enroll, call a vendor or change a CRM record.
