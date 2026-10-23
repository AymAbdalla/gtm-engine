# Audit a CRM export

`audit_crm.py audit` reads an export and never writes to the CRM. It writes `audit.md`, `audit.json`, `fixes.csv` and `review-queue.csv`.

## The checks

"Open people" means people whose status is not in `stop_statuses` (hold, booked, not_interested, wrong_person, left, do_not_contact, archived).

| Check | What it finds | Becomes |
|---|---|---|
| Do-not-contact only in notes or tags | an opt-out tag in `dnc_tags` (opted_out, dnc_all) or a note asking not to be contacted, while the status is still open | ticket: status to do_not_contact (step 1) |
| Left only in tags | a tag in `left_tags` (moved) while the status is still open | ticket: status to left (step 1). Never do_not_contact: leaving is not an opt-out. |
| Bounced still usable | a tag in `channel_block_tags.email` (bounced) while email_status is not invalid | ticket: email_status to invalid |
| | a bounced tag with no email at all | review: likely a call outcome logged as a bounce |
| Out-of-ICP still active | active accounts the shared fit rule puts out: size, country, industry or tech, or competitors, customers, partners. A blank field is unknown, not out, and is never ticketed | ticket: status to `audit.out_of_icp_status` (default hold) |
| Sequence problems | active enrollments for people who are stopped (`stop_statuses`), opted out (`dnc_tags` or a do-not-contact note), possibly left (`left_tags`), bounced or invalid | ticket: close (step 1) |
| | active enrollments overdue by more than `audit.overdue_days` | ticket: close (step 5); past repliers also go to review as re-entry candidates |
| | a person in more than one active sequence | review |
| Duplicate accounts | same domain | review: safe merge |
| | same name after removing legal words (inc, llc, co...) but a different domain | review: possible duplicate |
| Email domain mismatch | at least `domain_min_people` people and at least `domain_min_share` of the account's work emails on one other domain | ticket: change the account domain |
| | fewer than that | review, person by person |
| Stale flags | a short-term tag (this_week, call_today) with no touch in `audit.stale_days` | ticket: remove the tag |
| Empty accounts | active accounts with no open people | enrichment list |
| No channel | open people with no email and no phone | enrichment list |

Merges, unclear domains and double enrollments are never tickets. A person decides them.

## The health score

```
health = 100 x (1 - sum(weight x sqrt(share)) / sum(weight))
```

`share` is affected divided by the check's population. The square root makes the first problems count the most, so a small leak still moves the score. Only checks that ran count. Grades: A 90+, B 80+, C 70+, D 60+, F below. Weights live in `audit.weights`.

## The fix order

1. Stops: do-not-contact fields, close sequences to dead or blocked people
2. Suppression fields: bounced emails to invalid
3. Exclusions: out-of-ICP accounts off active
4. Bounce triage: real bounces vs mis-logged call outcomes
5. Sequences: close overdue enrollments, re-enter past repliers by hand
6. Records: merges, account domains, stale flags
7. Enrichment last

Stops come first because they are the only fixes where waiting can hurt someone. Enrichment comes last because it costs money and is wasted on records that are about to be closed or merged.

## The report

`audit.md` follows the same order every time, so nobody reads more into it than it says:

1. **Scope and limits** first: how many accounts, people and sequence rows were read, how many people were checked and how many were skipped because their status already stops contact, which checks ran and which did not (with the reason), and what the audit cannot see.
2. **Verdict**: "Blockers found within scope" when there are stop tickets (step 1), otherwise "No blockers found within scope". It never says the CRM passes, because it only covers these files and checks.
3. Health score and the check table.
4. **Findings**: one block per check that found something, each with an Evidence line (affected of total), a Fix line (its step in the fix plan) and a Verify line (export again, rerun, expect 0). Every ticket in `fixes.csv` also has its own `verify` column.
5. The fix plan and the review queue.

