# Example: Ledgerline signal-led outbound

Made-up data. Ledgerline is a fictional company selling spend-management software to finance teams.

- `motion/map.json`: 13 stages, from pulling public signals to the weekly funnel review, with one SDR (`rep`), an account executive (`ae`), a scheduled builder and an executor.
- `motion/map.md` and `motion/checks.md`: what `check_map.py` writes for it. The map is clean. The pick is S12 "Log outcomes and set the next step": mechanical, low risk if automated wrong, high cost if left manual, and the stage where the most accounts go cold. S09 "Find direct dials" is listed as not ready (clean the data first). S13 "Sync the CRM" is left out of the pick because it is already at the top automation level (`draft`).
- `broken/motion/map.json`: the same motion with two mistakes. S12 points to a stage S99 that does not exist, and the reply decision S08 has only its "booked" branch. The check reports 5 findings and 1 unresolved reference: the missing stage, the one-branch decision and its missing "else", and, as a result of the lost branch, S12 with no way in and S12 to S14 cut off from the start. Fix the decision first and three of the five go away. Because S12 and S13 now have findings, both are left out of the pick (map.md says why), and the pick falls to S04 "Build the play and pick seats".

Run from this skill's folder:

```
python3 scripts/check_map.py --workspace assets/example --out <empty folder>
python3 scripts/check_map.py --workspace assets/example/broken --out <empty folder>
```
