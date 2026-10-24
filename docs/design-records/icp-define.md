# Design record: icp-define (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries). Status: built, tested, design record written after the first build and checked against it.

## Job

A GTM engineer or founder needs the target market written down as one testable config (`gtm.json`) and a one-page `icp.md` that every other aym-gtm skill reads. The skill interviews the user or reads their notes, records where each answer came from, checks the config with a script, sorts an accounts list in or out with one reason each, and sizes segments as estimates, not forecasts. It declines list cleaning (data-quality), signal scoring (signal-score), building the books (account-book) and writing outreach (outreach-draft).

## Library queries

| Query | Returned |
| --- | --- |
| `ICP`, `ideal customer profile`, `segment`, `points`, `exclusion`, `region title`, `region`, `material decision` | no match |
| `market` | market-size-bands-with-noise |
| `weighted` | explainable-weighted-score |
| `decision` | user-decision-frontier, decision-map-with-fog, storyboard-before-render, exact-target-readback, installed-toolkit-review, persist-resumable-state |
| `missing` | preserve-missingness, test-observed-failure-before-fix, closed-roster-integrity, health-coverage-normalization, review-finding-truth-and-action, stop-on-invalid-input |
| `source` | explicit-edit-maps, scoped-finishing-chains, skill-authoring-as-release-process, rebuild-keeps-user-edits, editable-evidence-lineage, parameterized-host-emission |
| `estimate` | claim-vs-measurement-lineage |
| `config` | confirm-before-persistent-config, permission-scoped-capability-advertising |
| `interview` | cold-start-demo-script |
| `--id evidence-classes`, `--id domain-specific-constraints-stay-local` | read directly |

The library has no entry for ICP definition itself, segment design, persona ladders or the region-in-title rule. Those parts are an original design from the author's own outbound method.

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| market-size-bands-with-noise | Sizing must be honest: sourced count, noise discount from a 25-row sample, two significant figures, band label, "estimate, not forecast", serviceable revenue only as a hypothesis. | `scripts/icp_check.py` (`market_estimates`, `two_sig`, `band_label`), `references/market-size.md` |
| explainable-weighted-score | Account points drive ranking downstream, so each part must be visible and the weights editable. | `scripts/icp_check.py` (`classify_account`: `account_points` plus new `points_detail`), weights in `gtm.json` `scoring.account` |
| evidence-classes | Every answer is tagged evidence, judgment or default; guesses are written as hypotheses with the test that would settle them. | `references/interview.md`, SKILL.md steps 1 and 3 |
| preserve-missingness | Unknown headcount means "enrich first", not "out". A count with no source is rejected, not shown as zero. | `classify_account` (`unknown`), `validate_config` (count without source) |
| confirm-before-persistent-config | `gtm.json` is shared by ten skills; revising it happens only after the user agrees. | SKILL.md Boundaries |
| claim-vs-measurement-lineage | Market numbers keep their source and never become a forecast. | `references/market-size.md` "What not to claim" |

## Declined

| Mechanic | Reason |
| --- | --- |
| user-decision-frontier | Asks a frontier of questions in one round. The house rule is one question at a time in chat, so the interview asks one at a time and records the basis of each answer instead. |
| decision-map-with-fog | Useful for multi-stage design, but ICP choices are few and written as hypotheses in `icp.md`; no separate map needed. |
| cold-start-demo-script | Matched the word "interview" (job interviews), not the ICP interview. Belongs to create-my-portfolio. |
| rebuild-keeps-user-edits | account-book's job, not this one. |
| domain-specific-constraints-stay-local | Read for scope; the skill already keeps employer data out and uses made-up examples. No change needed. |
| permission-scoped-capability-advertising, closed-roster-integrity, health-coverage-normalization, stop-on-invalid-input, others above | Wrong job (tool exposure, artifact rosters, checker coverage, media inputs). |

## Conflicts resolved

- Interview style: frontier questions (library) versus one question at a time (the house rules). House rules win.

## Acceptance checks

- `tests/test_gtm_icp_define.py`: `test_example_config_is_clean`, `test_count_without_source_is_rejected`, `test_noise_adjustment_and_band`, `test_two_significant_figures`, `test_sam_only_with_value_and_share`, `test_unknown_headcount_is_not_out`, `test_segment_and_points` (now also checks `points_detail`), `test_reason_order_relationship_first`, `test_refuses_to_overwrite_input`, and the shared-key checks.
- `scripts/icp_check.py` on `assets/example/` (6 in, 8 out, 1 unknown).
- Two fresh-session trials (2026-10-20) used this skill to write `gtm.json` from a stated ICP.

## Gap found and fixed

- explainable-weighted-score asked for a visible breakdown; the script only wrote the total. Added `points_detail` (for example `sweet_spot 3; segment_match 1; tier P1 3`) to `accounts-icp.csv`, documented in SKILL.md step 5, tested in `test_segment_and_points`.

## Open gaps

- The sparsity probe (a filter that drops more than 90 percent of a count is a data gap) is guidance in `references/market-size.md`, not computed, because the script never sees the filtered and unfiltered counts. Proposal: accept an optional `unfiltered_count` per segment and flag the drop automatically.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: preserve-missingness (a blank field is unknown, never out), extend-owning-skill-before-new (the fit rule lives in one shared module, not a new skill).

Changed:

- One shared fit rule, `scripts/gtm_fit.py`, copied byte for byte into icp-define, data-quality, account-book and signal-score; `tests/test_gtm_shared.py` fails if the copies differ. Blank country, industry, headcount or tech is unknown; any known out reason wins.
- Optional `icp.technographics` (`required_any`, `excluded`) against an accounts `tech` column.
- Won deals check: `input/won-deals.csv` reports the share inside the ICP and names the rest.
- `icp.review_by` date: the check warns once it has passed. New `--today` and `--won` options.
- Step 2 says which sections the interview fills and which keep labelled defaults; step 4 lists errors and edits only after the user agrees; `references/config.md` covers all sections (test).

Checks: `tests/test_gtm_shared.py` (probe verdicts, tech rule, copy match); `tests/test_gtm_icp_define.py` WonDealsAndReviewTests.

Second review: an AI-assisted check pass followed on Oct 22 (findings fixed below).

Second review (Oct 22) findings fixed: `gtm_fit.py` (all four copies) treats "nan" and "inf" headcounts as unknown, and `icp_check.py` no longer crashes on them. A won-deals file needs only `account_id`; deals the rule cannot judge are listed as unknown, not outside. Tests: NotANumberTests, WonDealsAndReviewTests.
