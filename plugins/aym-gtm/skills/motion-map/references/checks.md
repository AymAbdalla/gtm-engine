# What check_map.py checks

A map is **clean** only with zero findings and zero unchecked items. Unresolved references are always listed, even when there are none, so nothing goes missing quietly.

| Code | Check | Example finding |
| --- | --- | --- |
| G1 | Every edge, start, end, role and system name points to something that exists | edge points to stage 'S99', which does not exist |
| G2 | Every stage has a way in (except the start) and a way out (except the ends) | no way out: this stage leads nowhere and is not marked as an end |
| G3 | A decision has at least two branches, each with a condition, and one for anything else | no branch for anything else |
| G4 | The start can reach every stage | cut off: the start stage can never reach these stages |
| R0 | Values come from the allowed lists (kind, level, waste, role kind) | automation level must be one of ... |
| R1 | Roles exist; each system has one operator; a stage writes only to systems its doer operates | rep writes to crm, but its one operator is executor |
| R2 | A stage that can't be undone never runs automatically and names a human approval point; a stage that writes to a live tool that sends or books is treated as one, unless `irreversible_override` says why not | writes to sequencer, which sends or books: mark it irreversible, or give irreversible_override |
| R3 | The scheduled builder never writes to a live system | the scheduled builder writes to live system crm |
| R4 | The executor never does judgment work | the executor is doing judgment work |
| R5 | Nothing is automatic or batch while its readiness lists something missing | automated while not ready |
| R6 | A model never owns a consequential gate or an exact fact | a model owns a consequential gate |
| R7 | Every automatic stage passes the loop check and has a state file, a do-not-retry list and a stop after a few identical runs | loop check fails: no automatic check can fail the work |

**Not checked** lists answers the map does not give: a missing trigger, owner, work type, tier, readiness block (or a readiness block with no `missing` list), loop block or decision answer. Fill them in with the user, or say plainly that the map is incomplete. Never invent the answer to make the check pass.

One mistake can cause several findings. In the broken example, one decision losing its "else" branch also leaves the logging stage with no way in and cuts off the stages after it. Fix the first cause, then rerun.

## The diagram

The Mermaid flow shows decisions as diamonds and labels each edge with its condition. Above `motion.max_nodes` stages (default 15), it shows only the stages with the most connections and says so; the stage table lists every stage. Edges to missing stages are left out of the diagram and listed in checks.md.
