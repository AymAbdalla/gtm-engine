# Design record: motion-map (aym-gtm)

Date: 2026-10-20. Built with build-skill against the mechanics library (200 entries).

## Job

Map a sales motion stage by stage, check the map for gaps, decide who owns each decision, and pick the one step to automate first, with a loop check before anything runs on a schedule. The caller is designing or changing a process, or answering an interview take-home. It reads `motion/map.json` and writes `motion/map.md` and `motion/checks.md`. It declines doing the work of any stage (the other aym-gtm skills) and never changes a tool.

## Library queries

| Query | IDs returned |
| --- | --- |
| stage | stage-audit-binary-analysis, stage-ownership, proof-boundaries, branch-based-context-pointers, stage-card-readiness-and-ownership, staged-state-gates |
| readiness | stage-card-readiness-and-ownership |
| automate | stage-card-readiness-and-ownership, fail-closed-review-parser, cleanup-dry-run-and-residuals, automate-only-checkable-repeating-work |
| owner | stage-card-readiness-and-ownership, stage-ownership |
| handoff | stable-state-identities, stage-ownership, physical-artifact-production-handoff |
| decision | user-decision-frontier, decision-map-with-fog, storyboard-before-render, exact-target-readback, installed-toolkit-review, persist-resumable-state |
| loop | automate-only-checkable-repeating-work, review-receipt-and-delta-rereview, three-strike-hypothesis-loop, visual-baseline-fix-verify-loop, bounded-loop |
| graph | deterministic-first-graph-enrichment, graph-neighborhood-retrieval, task-graph-frontier |
| approval | plan-review-pipeline-with-eng-last, evidence-ledger-with-individual-remedy-approval |
| risk | multidimensional-risk, two-layer-command-guard |
| schedule | automate-only-checkable-repeating-work, sequence-date-math-with-shift |
| unresolved | decision-map-with-fog, working-list-preserves-decisions-across-review-passes |
| diagram, role, operator | no match |

## Selected

| Mechanic | Why | Where it lives |
| --- | --- | --- |
| stage-card-readiness-and-ownership | The skill's core: stage cards, the readiness ladder, decision ownership, RACI and one step to automate first. | `references/stage-cards.md`, `references/automation-pick.md` |
| stage-ownership | Three roles and one operator per system, each transition with an owner. | Rules R1 to R4 in `scripts/check_map.py`; `references/checks.md` |
| automate-only-checkable-repeating-work | The loop check before any automatic stage: repeats, a check that can fail it, a budget, sees its own results, state file with a do-not-retry list. | "Loop check" in `references/automation-pick.md`; rule R7 |
| bounded-loop | A loop stops after a few runs with the same result and hands the item to a person. | `stop_after_identical_runs`; `loop_max_identical_runs` |
| multidimensional-risk | The two risks (automated wrong, left manual) stay separate and are never merged into one score; the pick sorts by them in order. | "Two risks per idea" in `references/automation-pick.md`; `pick` |
| decision-map-with-fog (variant) | Unknown readiness stays listed as unknown with the questions to answer, instead of being guessed. | Unknown readiness in `map.md` |

## Declined

| Mechanic | Reason |
| --- | --- |
| deterministic-first-graph-enrichment, graph-neighborhood-retrieval, task-graph-frontier | Code graphs and task scheduling; the map's graph checks are simple structural rules (edges, reachability, branches). |
| user-decision-frontier, review-receipt-and-delta-rereview, three-strike-hypothesis-loop | Interview and review loops in the core skills, not process mapping. |
| plan-review-pipeline-with-eng-last, evidence-ledger-with-individual-remedy-approval, two-layer-command-guard | Different approval and safety domains. |
| sequence-date-math-with-shift | Belongs to daily-plan. |
| stage-audit-binary-analysis, staged-state-gates and other single-word hits | Unrelated. |

## Conflicts resolved

- A clean map versus missing answers: a map counts as clean only with zero findings and zero unchecked items; missing card answers are "not checked", never passed.
- Picking a step versus safety: stages with findings, stages already at the top level, high-risk stages and stages with unknown readiness are never picked, and the report says why each was left out.

## Gaps found

None. Every selected mechanic is implemented and tested.

## Acceptance checks

`tests/test_gtm_motion_map.py` (25 tests), including `test_no_way_in_no_way_out_and_cut_off`, `test_decision_needs_two_conditioned_branches_and_else`, `test_unresolved_references_are_listed`, `test_one_operator_per_system`, `test_irreversible_needs_a_person`, `test_loop_check`, `test_pick_order_and_exclusions`, `test_stage_with_findings_is_never_picked`, `test_unknown_readiness_is_never_ready` and `test_clean_example_matches_committed_outputs`. `check_skill.py` on the skill folder.

## Open gaps

None found in this pass.

## Revision 2026-10-22: quality review fixes

Source: an Oct 22, 2026 quality review of the ten skills and the fix plan that followed it. Built as a bounded revision; mechanics library topics checked first: `fit gate`, `live deal`, `send gate`, `preserve missingness`, `copy lint`, `cohort`, `holdout`, `stated default`.

Selected: staged-state-gates (provisional pick), separate-decide-from-execute.

Changed:

- With any G1 to G4 finding, the pick is labelled provisional in the output and map.md.
- A stage writing to a live system that sends or books counts as irreversible unless it gives `irreversible_override`; systems may say `sends: true`.
- Optional `measure` block plus `--today`: weekly volume counted from `log/activity.csv`, labelled measured.

Checks: `tests/test_gtm_motion_map.py` HonestPickTests; the broken example's expected `map.md` and one assertion now carry the provisional label.

An independent review followed on Oct 22.
