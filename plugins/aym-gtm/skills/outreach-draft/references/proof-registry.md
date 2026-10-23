# Proof registry

The proof registry is the only place a seller claim can come from. If a claim is not in it as `VERIFIED`, the message cannot make that claim.

File: `outreach/proof.json`

```json
{
  "entries": [
    {
      "id": "pr-01",
      "status": "VERIFIED",
      "text": "Finance teams on Ledgerline close the month 3 days sooner.",
      "source": "case-studies/closing-time.md",
      "verified_date": "2026-09-15",
      "size_band": "200-2000",
      "personas": ["cfo", "controller"]
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `id` | Short stable id. Drafts and templates point to it with `proof: pr-01`. |
| `status` | `VERIFIED`, `SLOT` or `QUARANTINED`. |
| `text` | The exact line a message may use. Numbers in a message must appear here. |
| `source` | Where the claim comes from: a file, a link, a signed case study. |
| `verified_date` | When someone last checked the source. Older than `proof_max_age_days` (default 365) gives a re-check note. |
| `size_band` | Company size the proof comes from. Use it with prospects of a similar size. |
| `personas` | Persona ids allowed to read this claim, or `["all"]`. |
| `claim`, `note` | Optional. For a SLOT, describe the claim you want. For QUARANTINED, say why. |

## Statuses

- **VERIFIED**: has text, a source and a date. Can be used, one per message. The checker fails a VERIFIED entry that is missing any of the three.
- **SLOT**: a claim you want but cannot back yet. The empty slot is a to-do, not permission. Drafts that use it fail.
- **QUARANTINED**: once used, now unsupported (source lost, number changed, customer asked to be removed). Never used. Keep it so nobody adds it back by accident.

## Rules

- Add a claim only with its source in hand. Copy the number exactly.
- To make a proof anonymous, remove the customer name. Never change the number.
- When a source changes, update the entry and its `verified_date`, or quarantine it.
- One proof line per message. Pick the one that fits the persona and the company size.
