# Map checks

Result: **not clean**. 5 finding(s), 0 unchecked item(s), 1 unresolved reference(s). 13 stages checked.

A map is clean only with zero findings and zero unchecked items.

## Findings

| Code | Where | Finding |
| --- | --- | --- |
| G1 | S12 | edge points to stage 'S99', which does not exist |
| G2 | S12 | no way in: nothing leads to this stage |
| G3 | S08 | decision has 1 branch(es); it needs at least 2 |
| G3 | S08 | no branch for anything else: add one with when "else" |
| G4 | S12, S13, S14 | cut off: the start stage can never reach these stages |

## Not checked

None.

## Unresolved references

- S12: edge to missing stage 'S99'

Codes: G1 missing reference, G2 no way in or out, G3 decision branches, G4 cut off, R0 bad value, R1 roles and one operator per system, R2 a person commits, spends or sends, R3 builder touches a live tool, R4 executor doing judgment work, R5 automated while not ready, R6 decision ownership, R7 loop check.
