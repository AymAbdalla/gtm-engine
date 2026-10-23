# Picking what to automate

## Readiness ladder

Go up one rung at a time. Stop at the first rung that fails.

1. **What can be seen today?** The fields, lists and logs that exist now.
2. **What is missing?** Fields, owners, statuses, ids, a log that nobody keeps.
3. **Cleanup order.** What to fix first, usually with data-quality or account-book.
4. **Only then: automation ideas.**

"Not ready, clean this first" is a valid and often the best answer. Automating a stage on top of dirty data makes the mess faster. The check flags any stage set to automatic or batch while its readiness still lists something missing.

## Who owns each decision

For each decision, answer six questions:

1. Is the answer an exact fact (a date, a status, a number)? Then a rule owns it.
2. Is it consequential (money, a message going out, a record changing for good)?
3. What happens if a model gets it wrong?
4. Can a check catch a wrong answer before it matters?
5. How often does it come up?
6. Who is accountable when it goes wrong?

Rules own exact facts and consequential gates. A model may own interpretation (what a reply means, which angle fits) when a wrong answer is cheap and a check or a person catches it. Use the least control that prevents a failure you cannot accept. The check flags a model owning a consequential gate or an exact fact.

## Two risks per idea

Rate each automation idea on both:

- **If automated wrong:** low, medium or high. High is excluded from the pick.
- **If left manual:** what it costs to keep doing by hand (time, missed follow-ups, deals going cold).

## The one step to automate first

From mechanical stages that are manual or batch, can be undone, and not high risk if automated wrong, these can never be picked:

- **A stage with any finding** in checks.md (a broken edge, no way in or out, a bad decision, cut off, or a rule finding). Fix the map first; automating a broken step makes it break faster.
- **A stage already at the top automation level** (`draft`). A person keeps the final step, so there is no level left to move it to.
- **A stage whose readiness is unknown**: no readiness block, or no `missing` list. Unknown is never the same as ready. map.md lists these stages with three questions to answer: what can be seen today, what is missing, and what must be cleaned first.
- **A stage that is not ready**: its `missing` list has something in it. map.md lists its cleanup.

map.md says which stages were left out and why. While the map has any flow finding (G1 to G4), the pick is shown but labelled provisional: fix the flow first, rerun, then trust it.

From what is left, pick by:

1. lowest risk if automated wrong
2. then where deals most often go cold (`cold_rate`)
3. then the most minutes a week by hand (`volume_per_week` x `minutes_per_item`; a stage with a `measure` block uses the weekly count from the activity log instead of an estimate)

Move it up one automation level (none to observe, observe to suggest, suggest to draft), not straight to fully automatic. The script names the pick, the next in line, and the stages that need cleanup first.

## Build order

1. Do the job once by hand and watch it succeed.
2. Turn the steps into a skill or a script.
3. Wrap it in a loop with stop rules.
4. Schedule it last.

## Loop check

Before any stage runs on its own (tier `automatic`), all four must be yes:

1. It repeats weekly or more.
2. An automatic check can fail the work. "The agent says it looks fine" is not a check.
3. A budget caps runs, time and cost.
4. It can see its own results: logs, outputs, the files it changed.

Its `loop` block also names:

- `state_file`: where each run records what it did, so the next run resumes instead of starting over.
- `do_not_retry`: things that failed in a way a retry cannot fix.
- `stop_after_identical_runs`: progress is judged by outcomes, not activity. After this many runs with the same result (default limit 3), stop and hand the item to a person.

Judge a running loop by the share of runs whose changes a person accepts. Below about half, fix it or turn it off.
