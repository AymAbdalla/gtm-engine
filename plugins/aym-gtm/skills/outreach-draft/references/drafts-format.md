# Drafts file format

One Markdown file per batch: `outreach/drafts/YYYY-MM-DD.md` (then `-2`, `-3` if the day already has one). The checker reads this exact shape.

````markdown
# Drafts 2026-11-02

## d-001 | Dana Okafor, Controller, Brightmill
- person_id: p-014
- account_id: a-03
- persona: controller
- sequence: seq-trigger-finance
- step: 1
- channel: email
- thread: new
- angle: trigger
- proof: pr-01
- why_now: Brightmill posted an AP lead opening on its careers page on 2026-10-20.
- source: https://brightmill.example/careers/ap-lead
- source_date: 2026-10-20
- status: ready
- [ ] sent

Subject: Brightmill month end

Body:
Hi Dana, ...
````

## Parts

- **Heading**: `## <draft id> | <name>, <title>, <company>`. Each draft starts with `## `.
- **Fields**: one `- key: value` per line before `Subject:` and `Body:`.
  - Required: `person_id`, `channel` (`email`, `linkedin`, `call`), `thread` (`new`, `reply`), `angle`.
  - First touches (`thread: new` on email or LinkedIn) also need `why_now`, `source` and `source_date` (`YYYY-MM-DD`).
  - Optional: `account_id`, `persona` (needed when `proof` is used), `play_id`, `sequence`, `step`, `proof` (comma list of registry ids), `status` (`ready` or `needs_human`).
- **Sent checkbox**: `- [ ] sent`. The user changes it to `- [x] sent` after sending by hand. A ticked draft that fails the check is reported as a failure. `scripts/record_sent.py` turns each ticked draft into one `sent` row in `log/activity.csv` (activity id `draft-<file name>-<draft id>`, so a rerun adds nothing). Optional fields `play_id`, `sequence` and `step` are copied into that row.
- **Subject**: `Subject: ...` for a new email thread only.
- **Body**: everything after the `Body:` line until the next `## ` heading.

## Verdicts

- `PASS`: every check passed. Still read it and open the source before sending; the checks cannot prove every sentence true.
- `NEEDS_HUMAN`: has a `{{variable}}` gap, `status: needs_human`, a possible seller claim with no proof, or a fact the `why_now` line does not state. Cannot be sent until a person fills or checks it.
- `FAIL`: breaks a rule. The reason is printed under it. The script exits with code 1.
