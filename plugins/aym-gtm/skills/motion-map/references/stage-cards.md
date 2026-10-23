# Stage cards, roles and handoffs

## The stage card

Every stage gets a card with these answers. A missing answer shows up in checks.md as "not checked".

- **Trigger:** a clock, an event or a person's action.
- **Work:** mechanical (rules can do it) or judgment (someone has to interpret).
- **Automation level** (how much a tool does): `none`, then `observe` (a tool watches and reports), then `suggest` (a tool proposes, a person decides), then `draft` (a tool prepares the work, a person checks and finishes it). There is no level above draft for anything that sends, spends, books or publishes. A person always commits, spends or sends.
- **What a person reads** before the work moves on.
- **Approval point:** the exact moment a person says yes.
- **Owner** and **off switch:** who answers for it and how to stop it fast.

## Automation tiers

| Tier | Means |
| --- | --- |
| automatic | Runs on its own. Needs a passing [loop check](automation-pick.md#loop-check) and must never do something that can't be undone. |
| batch | A tool prepares a batch; a person approves each run. |
| manual | A person does it. |
| blocked | Should not be automated now, with the reason written down. |

## Three roles, one operator per system

- **The human** makes the calls, judges replies, approves lists and presses send.
- **The scheduled builder** writes files and plans only. It never touches a live tool (CRM, sequencer, calendar, inbox).
- **The executor** applies plans a person approved. It never writes copy and never picks who to contact.
- **One operator per system.** Each system names the one role that writes to it. Two writers to the same system cause silent overwrites. The check flags any stage that writes to a system it does not operate.

## RACI

For each stage: who **does** it (R), who **owns** the result (A), who is **asked** first (C), who is **told** after (I). Keep A to one role.

## Exceptions

A short "usually X, sometimes Y" line wherever the happy path is not the whole story. Exceptions are where automation breaks first, so read them before picking what to automate.

## Waste at handoffs

Tag the handoff out of each stage with one word:

- **waiting**: work sits until someone gets to it
- **rework**: work comes back to be done again
- **handoff**: context is lost passing between people or tools
- **manual**: copying or retyping between tools

The tags show where time leaks. They do not, on their own, say what to automate.
