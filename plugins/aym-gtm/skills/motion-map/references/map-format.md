# map.json format

One file per motion at `<workspace>/motion/map.json`. Write it with the user, or draft it from their description and then confirm each stage with them. See the made-up example in `assets/example/motion/map.json`.

## Top level

| Key | What it holds |
| --- | --- |
| `motion` | `name`, optional `seller` and a one-line `summary`. |
| `roles` | Who does the work. Each has `id`, `label` and `kind`: `human`, `scheduled_builder` or `executor`. See [stage cards](stage-cards.md) for what each kind may do. |
| `systems` | Where the work lands. Each has `id`, `label`, `live` (true for a real tool such as a CRM, sequencer or calendar; false for plain files), `operator`, the one role that writes to it, and optional `sends` (true or false) to say whether writing to it sends or books. |
| `start` | The stage the motion starts at. Defaults to the first stage. |
| `ends` | Stages where the motion is allowed to stop. |
| `stages` | The stages, in the order you want them listed. |

## Stage fields

| Field | Meaning |
| --- | --- |
| `id`, `name` | Short id (S01, S02) and a plain name. |
| `kind` | `task` or `decision`. |
| `trigger` | `{"type": "clock" or "event" or "human", "detail": "weekdays at 7am"}`. |
| `work` | `mechanical` (same input gives the same output) or `judgment` (a person or a model has to interpret). |
| `owner` | The role responsible for the stage. |
| `raci` | `{"r": does it, "a": owns the result, "c": [asked], "i": [told]}`. Every name must be a role. |
| `systems`, `writes` | Systems the stage touches, and the ones it writes to. A stage may only write to a system whose operator is the role doing the work. |
| `inputs`, `outputs` | Files, lists or records in and out. |
| `volume_per_week`, `minutes_per_item` | Rough numbers to size the work. Estimates are fine; say so. |
| `cold_rate` | Share of items that go cold at this stage (0 to 1). An estimate is fine. |
| `automation` | `tier` (`automatic`, `batch`, `manual`, `blocked`), `level` (`none`, `observe`, `suggest`, `draft`), `human_reads`, `approval_point`, `off_switch`. |
| `readiness` | `visible_today`, `missing`, `cleanup`: the readiness ladder. `visible_today` must name at least one thing you can see today, and `missing` must be a list; write `[]` when nothing is missing. Without both, the stage's readiness is unknown and it can't be picked. A block with every list empty counts as unknown. |
| `next` | Edges: `[{"to": "S04", "when": "playable"}]`. A decision needs at least two branches, each with a condition, and one with `"when": "else"`. |
| `exceptions` | `[{"usually": "...", "sometimes": "..."}]`. |
| `waste` | The handoff into the next stage: `waiting`, `rework`, `handoff`, `manual` or `none`. |
| `risk` | `{"automated_wrong": low/medium/high, "left_manual": low/medium/high}`. |
| `irreversible` | true when the stage sends, spends, publishes, books or deletes. A stage that writes to a live system that sends or books (named like a sequencer, email, inbox, dialer, calendar, SMS or LinkedIn tool, or marked `sends: true`) is checked as irreversible unless `irreversible_override` gives the reason it can be undone. |
| `measure` | Optional: `{"channel": "call", "direction": "out", "outcomes": [...]}`. With `--today`, the check counts matching rows in `log/activity.csv` over the last four weeks and uses that weekly number instead of `volume_per_week`, labelled measured. |
| `loop` | Required when `tier` is `automatic`: see [automation pick](automation-pick.md#loop-check). |
| `decision` | Required on a decision stage: `question`, `owner` (`rule`, `model`, `human`), `exact_fact`, `consequential`, `if_wrong`, `check`, `accountable`. |

## Drafting a map from a conversation

Ask, one at a time, and write the answers straight into stages:

1. What starts the work? (a clock, an event, a person)
2. Walk me through one account from first sign to booked meeting. What happens next, and who does it?
3. Where do you decide something? What are the possible answers, and what happens for anything else?
4. Which tools does each step touch, and who is the only one who should write to each?
5. Roughly how many a week, and how long does each take?
6. Where do accounts most often go cold?
7. What usually happens, and what sometimes happens instead?
8. What would you need to see today to trust this step running without you?

Mark every number you estimated as an estimate in the stage's `exceptions` or in your report. Never fill a field with a guess the user did not confirm; leave it out, and the check lists it as not checked.
