# Fix tickets and the recheck

## fixes.csv

| Column | Meaning |
|---|---|
| `ticket_id` | T001, T002... in fix-plan order |
| `step` | 1 to 7 from the fix order |
| `record_type` | account, person or sequence |
| `record_id` | the record's ID. Sequence IDs are `person_id:sequence`. |
| `field` | the one field to change |
| `current_value` | what the export showed when the plan was made |
| `new_value` | the proposed value. Blank means clear the field. |
| `evidence` | why, in one line |
| `check_first` | what a person confirms before submitting |
| `verify` | how to prove the fix landed: what a fresh export should show (recheck then lists the row as already done) |

One field per row. If a record needs two changes, it gets two rows. The user's admin or the user submits them; this skill never does.

## Turning tickets into requests

When the user needs a request for an admin, group rows by `step`, then by `field`, and give each group one short request: what changes, how many records, the evidence pattern and the check. Put stops first. Keep IDs and values in the CSV, not in the message body.

## The staleness rule

A ticket is only safe while the record still holds `current_value`. Before submitting:

```
python3 <skill-dir>/scripts/audit_crm.py recheck --fixes fixes.csv --accounts fresh-accounts.csv --people fresh-people.csv --sequences fresh-sequences.csv --out recheck/
```

- `fixes-ready.csv`: the record still shows `current_value`. Safe to submit.
- `fixes-skip.csv`: the record already shows `new_value`. Nothing to do.
- `fixes-drift.csv`: the record changed to something else, or is gone. Do not submit. Re-plan it.

This is the same pattern for any write the user makes later: dry run first, skip what is already right, stop on drift.
