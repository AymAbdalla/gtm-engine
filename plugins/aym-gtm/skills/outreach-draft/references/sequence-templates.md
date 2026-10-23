# Sequence templates

A sequence is a fixed set of steps across channels. Templates live in `outreach/sequences.json`. The copy checker fills each variable with its example value and checks every step.

```json
{
  "sequences": [
    {
      "id": "seq-trigger-finance",
      "version": 1,
      "persona": "controller",
      "who": "Controllers at in-ICP accounts with a playable signal from the last 90 days",
      "angle": "trigger",
      "variables": {
        "first_name": {"description": "Prospect first name", "example": "Dana"},
        "company": {"description": "Account name as people say it", "example": "Brightmill"},
        "trigger_fact": {"description": "One sourced, dated fact in plain words", "example": "you are hiring an AP lead"}
      },
      "steps": [
        {"day": 1, "order": 1, "channel": "email", "thread": "new", "proof": "pr-01",
         "subject": "{{company}} month end", "body": "Hi {{first_name}}, ..."}
      ],
      "stop_rules": ["any reply", "meeting booked", "not interested", "wrong person",
                     "opted out", "email bounced",
                     "reply from anyone at the same account stops every sequence there"]
    }
  ]
}
```

## Fields

| Field | Meaning |
| --- | --- |
| `id`, `version` | Bump the version when you change copy, so results from old and new copy stay apart. |
| `persona` | Persona id the sequence is written for. Proof must be allowed for it. |
| `who` | Plain words: who goes into this sequence. |
| `angle` | Main angle. Steps can vary it; the draft records its own angle. |
| `variables` | Every `{{name}}` used, each with a description and an example. |
| `steps` | `day` (business day of the sequence, from 1), `order` (same-day order), `channel` (`email`, `call`, `linkedin`), `thread` (`new` or `reply`), `subject`, `body`, optional `proof`. |
| `stop_rules` | When a person leaves the sequence. |

## Rules the checker enforces

- The first step starts a new thread. Days never go backwards.
- A new email thread has a subject. Replies and non-email steps have none.
- Every variable used is declared with a description and an example. Unused variables get a note.
- Each step passes the copy rules with example values filled in.

## Rules for whoever runs the sequence

- Day `d` lands on start date plus `d - 1` business days. If a step is missed, later steps move by the same number of days.
- A step that cannot be done (no working phone, email fails the send gate, outside calling hours) is skipped, not counted as missed.
- One touch per person per day.
- Any stop rule ends the sequence. A reply from anyone at the account stops the whole account.
- A step with an unfilled variable is held for a person to fill.
