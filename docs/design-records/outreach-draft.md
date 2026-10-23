# Design record: outreach-draft (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries). Status: built, tested, two review rounds, design record written after the first build and checked against it.

## Job

A GTM engineer needs first touches and sequence steps drafted into a dated file a person reviews and sends by hand, each draft checked by a script against the copy rules, a proof registry of approved claims and a sourced, dated "why now" fact. A ticked "sent" box records that a person sent it. The skill never sends, enrolls or writes to a mailbox or CRM. It declines choosing accounts (signal-score, account-book), filling plays (play-build) and cleaning lists (data-quality).

## Library queries

| Query | Returned |
| --- | --- |
| `copy` | proof-registry-copy-lint |
| `proof` | proof-boundaries, escalate-proof-by-ambiguity, proof-registry-copy-lint |
| `draft` | human-ticked-draft-file, skill-authoring-as-release-process |
| `prose` | edit-prose-with-specific-checks |
| `test` | confirm-test-seams, bounded-test-evidence-modes, preregistered-single-variable-test, editorial-rules-need-calibration, skill-authoring-as-release-process, test-cheap-before-production |
| `variable` | preregistered-single-variable-test |
| `message` | message-to-destination-consistency, preregistered-single-variable-test |
| `claim` | cold-start-demo-script, report-simplification-delta, evidence-adjacent-delivery, evidence-classes, proof-registry-copy-lint, input-scope-bounds-completeness |
| `one primary` | many-options-then-user-choice |
| `angle` | no match |
| `--id` reads | why-now-or-weak-case, one-primary-action, machine-checkable-quality-bar, derive-state-from-append-only-log |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| proof-registry-copy-lint | Outbound copy must not invent claims: registry with VERIFIED, SLOT and QUARANTINED; a script checks word band, one question, dashes, links, banned phrases, variables, subject rules and that every number is backed. | `scripts/lint_copy.py`, `references/copy-rules.md`, `references/proof-registry.md` |
| human-ticked-draft-file | Every send stays a person's action; drafts go to a dated file with a sent checkbox, and the tick is recorded as a sent status. | `references/drafts-format.md`; new `scripts/record_sent.py` |
| why-now-or-weak-case | A first touch needs one sourced, dated fact; intent is never mentioned; no fact means "weak case", not invented urgency. | SKILL.md step 2, `lint_copy.py` first-touch checks |
| derive-state-from-append-only-log | Sends must reach the shared activity log so daily-plan, crm-sync and funnel-review compute state from it. | `scripts/record_sent.py` appends one row per ticked draft, idempotent by activity id |
| preregistered-single-variable-test | Each draft carries one angle tag so funnel-review can test angles later; this skill never calls a winner. | SKILL.md step 3 and Boundaries, `references/angles.md` |
| one-primary-action | One ask per message: exactly one question, and the email ends on it. | `lint_copy.py` question rule |
| editorial-rules-need-calibration | Hard rules are a house style and editable in `gtm.json` `copy`; the word band below the minimum is a note, not a failure. | `gtm.json` `copy`, `lint_copy.py` notes |

## Declined

| Mechanic | Reason |
| --- | --- |
| edit-prose-with-specific-checks | stop-slop is installed separately for prose; duplicating its rules here would drift. The copy lint covers outbound-specific rules only. |
| message-to-destination-consistency | Outreach has no landing page; the linked source is checked by the person before the first touch. |
| machine-checkable-quality-bar | Its adopted form is the test-weakening scan in check-this and implement-this. |
| proof-boundaries, escalate-proof-by-ambiguity | About evidence stages in engineering reports, not sales claims. |
| many-options-then-user-choice | Angle rotation across a batch already gives the user options without a separate choice step. |

## Acceptance checks

- `tests/test_gtm_outreach_draft.py` (26 tests), including `test_slot_and_quarantined_proof_fail`, `test_unbacked_number_fails`, `test_first_touch_needs_source`, `test_exactly_one_question_and_ends_on_it`, `test_subject_line_is_checked`, `test_verified_proof_without_source_fails`, `test_missing_default_proof_file_runs_with_empty_registry`, and the new `test_ticked_draft_becomes_one_sent_row_and_reruns_add_nothing`, `test_exact_send_time_and_dry_run`, `test_send_time_without_offset_is_refused`.
- Example lint run on `assets/example/outreach/drafts/2026-11-02.md`.
- Two independent review rounds and two fresh-session trials (2026-10-20).

## Gap found and fixed

- human-ticked-draft-file says the tick becomes a sent status on the next run. Nothing did that: a ticked draft never reached `log/activity.csv`, so daily-plan, crm-sync and funnel-review could not see the send. Added `scripts/record_sent.py` (append-only, idempotent by `draft-<file>-<id>`, `--dry-run`, `--sent-at`; otherwise noon on `--today` in the user's time zone with "send time approximate" in the notes). Documented as SKILL.md step 8 and in `references/drafts-format.md`; three tests.

## Open gaps

- On Python 3.8 there is no time zone database, so `record_sent.py` needs `--utc-offset=-04:00` or `--sent-at` there.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: proof-registry-copy-lint (extended), separate-decide-from-execute (PASS is a check result, not permission).

Changed:

- Truth checks: intent words fail; spelled-out numbers must be backed; seller-claim phrases with no proof and fact words missing from `why_now` make a draft NEEDS_HUMAN; the greeting must match the heading's first name.
- Book gate: when `book/people.csv` exists, a draft for someone not cleared on that channel fails (`--book`).
- Word lists live in `gtm.json` `copy` as editable defaults.
- SKILL.md says what the checker cannot prove, who owns the opt-out and address footer, and the description names the `log/activity.csv` write.

Checks: `tests/test_gtm_outreach_draft.py` TruthChecks (the review's two probe drafts); example batch verdicts unchanged; test fixture heading and one greeting aligned to Dana.

An independent review followed on Oct 22.

Independent review (Oct 22) findings fixed: Fewer false alarms: a hyphen joins words ("two-minute", "year-round"), `copy.number_ok_phrases` skips "first/second half", bare "looking into" left the intent list, and the greeting check allows short forms, a few nicknames, accents and "Hi there". A wrong accented name is still caught. Tests: TruthChecks.
