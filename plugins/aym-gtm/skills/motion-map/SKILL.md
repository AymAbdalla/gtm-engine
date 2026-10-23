---
name: motion-map
description: Map a sales motion stage by stage, check it for broken flows and unsafe automation, and pick the one step to automate first. Writes stage cards (trigger, work type, automation level, approval point, owner, off switch), RACI, waste, readiness, decision ownership, a loop check and a Mermaid flow. Use for "map our sales motion", "what should we automate first", "audit this GTM workflow", "is this ready to automate", or a take-home or audit of a sales process. Not for data, plays, plans or reports. Never changes a tool or CRM.
---

# Motion map

Draw how deals actually move, decide who owns each step, and pick one step to automate first. The answer is often "clean this first", and that is fine. The skill writes files only. It never changes a tool, a CRM, a sequencer or a schedule.

## If the script cannot run

This skill's results come from `scripts/check_map.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write `motion/map.md` or `motion/checks.md`, and do not call the map clean by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Drafting `motion/map.json` with the user is still your job; say it is unchecked. Give the user the command to run when they can: `python3 <skill-dir>/scripts/check_map.py --workspace <workspace>`.

## Inputs

`<skill-dir>` is this skill's folder; `<workspace>` is the user's GTM workspace (default `./gtm`).

- `motion/map.json`: the stages, roles and systems. Format and the questions to draft it: [map format](references/map-format.md).
- `gtm.json` (optional): the `motion` section (diagram size cap, risk order, which risk levels are never picked, loop limits). Every value is an editable default, not a standard.

If there is no map yet, draft one with the user, one question at a time, from [map format](references/map-format.md#drafting-a-map-from-a-conversation). Use their words for stage names. Leave out anything they did not confirm; the check will list it as not checked. Customer or employer details stay where the user is allowed to keep them. For a portfolio or interview piece, use made-up names.

## Steps

1. **Write or update `motion/map.json`** with the user. Fill a stage card for each stage ([stage cards](references/stage-cards.md)): trigger, judgment or mechanical, automation tier and level, what a person reads, approval point, owner, off switch, RACI, exceptions, waste.
2. **Run the check:**
   `python3 <skill-dir>/scripts/check_map.py --workspace <workspace>`
   It writes `motion/map.md` and `motion/checks.md`. Exit code 0 means clean, 1 means findings or unchecked items, 2 means the map or config could not be read.
   Add `--today YYYY-MM-DD` when stages have a `measure` block: their weekly volume is counted from `log/activity.csv` over the last four weeks and labelled "measured from the log" instead of an estimate.
3. **Fix the first cause, then rerun.** One broken branch can cut off several stages. Walk the user through checks.md, starting with G1 to G4 (the flow), then R2 (a person must commit, spend or send), then the rest. See [checks](references/checks.md).
4. **Climb the readiness ladder** for the stages the user wants to automate: what can be seen today, what is missing, the cleanup order, and only then ideas. See [automation pick](references/automation-pick.md).
5. **Settle decision ownership** with the six questions. Rules own exact facts and consequential gates; a model may own interpretation when a wrong answer is cheap and caught.
6. **Present the pick.** While the map has any flow finding (G1 to G4), the pick is labelled provisional: the map may not show the real work, so fix the flow before trusting it. Stages with findings, stages already at the top level (`draft`) and stages whose readiness is unknown are never picked; map.md says why each was left out and lists the readiness questions to answer. One step, moved up one automation level, with its two risks, the build order (by hand once, then a script or skill, then a loop, then a schedule) and the loop check it must pass before it runs on its own.

## Rules that matter most

- A person always commits, spends, sends, books or publishes. Nothing that can't be undone runs automatically. A stage that writes to a live tool that sends or books (a sequencer, inbox, dialer or calendar, or a system marked `sends: true`) counts as irreversible unless it gives `irreversible_override` with the reason it can be undone.
- The scheduled builder writes files only. The executor applies approved plans only and never writes copy or picks who to contact. Each system has one operator.
- Automating a stage that is not ready makes the mess faster. Clean first.
- Progress is judged by outcomes, not activity. A loop stops after a few runs with the same result and hands the item to a person.
- Never invent a number, an owner or a stage. Estimates are labeled as estimates.

## Outputs

- `motion/map.md`: the flow (decisions as diamonds, capped at about 15 stages with a pointer to the full table), roles and systems, the stage table, stage cards, RACI, exceptions, waste, readiness, decision ownership, and the automate-first pick with the next in line, stages to clean first, stages whose readiness is unknown (with the questions to answer) and stages left out of the pick with the reason.
- `motion/checks.md`: findings by code, items not checked, and unresolved references (always listed).

## Report

Tell the user: the files written, whether the map is clean (findings and unchecked counts), the top findings in plain words, the one step to automate first and why, what to clean first, and that nothing was changed in any tool.

## Try it

`python3 <skill-dir>/scripts/check_map.py --workspace <skill-dir>/assets/example --out <any empty folder>` checks a made-up 13-stage outbound motion (clean). `--workspace <skill-dir>/assets/example/broken` checks the same motion with an edge to a missing stage and a reply decision with one branch. See [the example notes](assets/example/README.md).
