---
name: outreach-draft
description: Write outbound emails, LinkedIn notes and call reasons for chosen prospects into a dated drafts file, then check every draft against the copy rules, the proof registry, the sourced why-now fact and the book's send gate. Each draft gets a "sent" box the user ticks after sending it themselves; recording ticked drafts appends them to log/activity.csv. Use to draft outreach, write a sequence step, check copy, or set up a proof registry or sequence template. Not for sending, enrolling, CRM or mailbox writes, picking accounts or cleaning lists.
---

# Outreach draft

Write short, true, specific messages a person can review and send. The model writes the words. The script checks the rules it can check: style, numbers, proof, the cited fact, words that hint at research interest, the greeting and the book's gate. It cannot prove every sentence is true, so a person still reads each draft and opens its source. Nothing leaves the files.

## If the script cannot run

This skill's results come from `scripts/lint_copy.py` and `scripts/record_sent.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write a lint report, and do not mark any draft as passed or append rows to `log/activity.csv` by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Writing drafts is still your job; label each one "not checked: the lint script did not run". Give the user the command to run when they can: `python3 <skill-dir>/scripts/lint_copy.py --workspace <workspace> --drafts <workspace>/outreach/drafts/<file>.md`.

## Ground rules

- **Never send.** No email, DM, enrollment, mailbox draft or CRM write. The user sends and ticks `sent`.
- **Every claim is true and sourced.** A fact about the prospect comes from a dated source (the `why_now` line). A fact about the seller comes from a `VERIFIED` proof entry. No source, no claim.
- **Do-not-contact always wins.** Skip anyone whose status is in `stop_statuses`, who has a tag in `dnc_tags` or `left_tags`, whose notes ask not to be contacted, or who fails the send gate.
- **Use only data the user is allowed to keep here.** Examples in this skill are made up.

## Inputs

Workspace folder (default `./gtm`):

| File | What it gives |
| --- | --- |
| `gtm.json` | The `copy` section: word band, question rule, banned items, angles. Defaults apply if missing. |
| `outreach/proof.json` | The proof registry. See [proof registry](references/proof-registry.md). |
| `outreach/sequences.json` | Sequence templates. See [sequence templates](references/sequence-templates.md). |
| Who to write to | Playable rows from `signals/scored.csv`, people with `send_ok` = `yes` (first touches) or `followup_ok` = `yes` (next step of their own sequence) in `book/people.csv`, or a list the user names. |
| `book/people.csv` | When it exists, the checker fails any draft whose person is not cleared for that channel (`send_ok`, `followup_ok`, `call_ok` or `linkedin_ok`), or is not in the book. |

If there is no proof registry, write drafts with no seller claims and offer to set one up. The checker runs without one; do not create an empty file. If there is no sequence, write first touches only.

## Steps

1. **Pick the people.** Both email flags in `book/people.csv` already leave out non-buyers, excluded accounts (competitor, customer, partner, parent decides), accounts on hold and accounts with a live deal. For other channels, use `call_ok` or a working LinkedIn profile. Skip anyone the ground rules above block.
   - **First touch:** only people with `send_ok` = `yes`. That flag is `no` for anyone already in a sequence.
   - **Follow-up step:** only people with `followup_ok` = `yes` whose `sequence` is the sequence the step belongs to, at the step that is due.

   Say who you skipped and why.
2. **Check the fact.** Each first touch needs one `why_now` fact with `source` and `source_date`. Use only what the source says. Topic intent data is timing only: never mention it in the message. If there is no fact, write "weak case" in your report and do not invent urgency.
3. **Choose sequence, step and angle.** One angle per draft, from the [angle list](references/angles.md). Vary angles across the batch. Record the angle tag on each draft.
4. **Write.** Follow the [copy rules](references/copy-rules.md). Fill variables only from the data. If a value is missing, leave the `{{variable}}` in place and set `status: needs_human`.
5. **Save** to `outreach/drafts/YYYY-MM-DD.md` in the [drafts format](references/drafts-format.md). If that file exists, write `YYYY-MM-DD-2.md` and so on. Never overwrite a drafts file.
6. **Check.** Run this, where `<skill-dir>` is this skill's folder and `<ws>` is the workspace:
   ```
   python3 <skill-dir>/scripts/lint_copy.py --workspace <ws> --drafts <ws>/outreach/drafts/<file>.md --report <ws>/outreach/lint-report.md
   ```
   Add `--sequences <ws>/outreach/sequences.json` when you changed a template. The checker reads the subject line and the body.
7. **Fix and recheck.** A `NEEDS_HUMAN` draft that names a possible seller claim or a fact missing from `why_now` waits for a person to check the source; do not reword it to slip past the check. Rewrite a failing draft at most twice. Never fix a failure by adding a new claim, switching to a `SLOT` or `QUARANTINED` proof, or removing the source. If it still fails, drop it and list it in the report.
8. **Record what was sent.** After the user sends by hand and ticks `- [x] sent`, run:
   ```
   python3 <skill-dir>/scripts/record_sent.py --workspace <ws> --drafts <ws>/outreach/drafts/<file>.md --today <YYYY-MM-DD>
   ```
   It appends one `sent` row per ticked draft to `<ws>/log/activity.csv` so daily-plan, crm-sync and funnel-review see it. Rerunning adds nothing new. Add `--sent-at <time with offset>` when the user knows the send time; otherwise the row says the time is approximate. Use `--dry-run` to preview.

## Boundaries

- Sending, scheduling, enrolling and CRM updates are the user's actions. Say so if asked, and stop at the drafts file.
- The opt-out line and postal address that commercial email needs (US law applies to business email too) are added by the user's sending tool, not by these drafts. Before the first send, ask the user to confirm their sequencer adds a compliant footer.
- A `SLOT` proof means the claim cannot be made yet. A `QUARANTINED` proof is never used.
- Judging which angle works belongs to a later review once enough messages have gone out. Do not call an angle a winner from a handful of sends.

## Report

- Drafts file path and lint report path.
- Counts: PASS, NEEDS_HUMAN, FAIL, dropped, skipped (with reasons). PASS means the checks passed, not that every sentence is proven true.
- Angles used in the batch.
- What needs the user: fill the `needs_human` gaps, open each source before the first touch, send by hand and tick `sent`.
- What this skill did not do: send, enroll, or write to any system. Its only write outside the drafts file is appending ticked sends to the workspace activity log.
