# Send gate

A person may go into an email send list only when every check passes. Each setting lives in `gtm.json` and is an editable default. `send_ok` is `yes` or `no`, and `send_block_reason` lists every check that failed, so the user sees all of them at once.

## Checks for every channel (email and calls)

| Check | Setting | Blocks when |
|---|---|---|
| Person status | `stop_statuses` (default hold, booked, not_interested, wrong_person, left, do_not_contact, archived) | status is in the list |
| Opt-out tags | `dnc_tags` (default opted_out, dnc_all) | any tag is in the list. The book also sets status do_not_contact. |
| Left tags | `left_tags` (default moved) | any tag is in the list. The reason asks you to set status left if true; it never sets do_not_contact. |
| Do-not-contact notes | `clean.dnc_note_patterns` | the notes contain a phrase such as "do not contact" or "unsubscribe" |
| Not a buyer | `not_buyer_titles` | the title matches, for example a sales rep or an intern |
| Excluded relationship | `icp.exclude_relationships` (default competitor, customer, partner, parent_decides) | the account's relationship is in the list |
| ICP fit | the `icp` section, through the shared fit rule | the account is outside the ICP (strategy hold), or a field the rule needs is blank: "fit unknown: enrich first" |
| Account strategy | fixed | the account's strategy is excluded, hold, or live. A live deal belongs to its owner, so outbound stays off. |

## Email checks (`send_gate`)

| Check | Default | Blocks when |
|---|---|---|
| Email tags | `channel_block_tags.email`: bounced | any tag is in the list |
| Email present | always | no email |
| Catch-all | on | `email_status` is catch_all. A high vendor score never clears it. |
| Email status | verified only | status is not in `email_status_ok` |
| Email score | 80 | score is blank or below the floor. Fail closed: no score means no send. Set `min_email_score` to `null` to turn the check off. Scores like "1,00" are read as numbers. |
| Own domain | on | the email's domain is not the account's `domain` or one of its `other_domains` (subdomains count) |
| Country | US, CA | the person's country (or the account's, if blank) is not on the list |
| Sequence | first touches only | the person is already in a sequence (`send_ok` only; see follow-ups below) |

## Follow-ups

`followup_ok` is `yes` when every check above passes except the sequence rule, and the person is in a sequence. It means the next step of their own sequence may be drafted. `followup_block_reason` lists what failed, including "not in a sequence". Any reply stops follow-ups: a person with a tag in `book.reply_tags` (default `replied`, `past_reply`, `not_now`) gets `followup_ok` no, and so does everyone at the same account. A person handles replies, not the sequence. A first touch always needs `send_ok`.

## Call checks

`call_ok` uses the checks for every channel, the `channel_block_tags.call` tags (default dnc_phone, phone_failed) and a missing phone. A person can be callable while blocked for email. Calling hours and local do-not-call rules belong to the user's dialer and region; this skill does not judge them.

## LinkedIn checks

`linkedin_ok` uses the same checks for every channel, the `channel_block_tags.linkedin` tags and a missing LinkedIn URL. A person blocked for email and calls only because they have no email or phone can still pass. A person blocked because of who they are or where they work (a stop status, an opt-out, a not-buyer title, an excluded, held or live-deal account) never passes on any channel.

## Export

`--export` writes only people whose `send_ok` is `yes`. Everyone else at the named accounts goes to `export-left-out.csv` with their reasons. An account id that is not in the book stops the run with an error, so a typo never produces an empty list without warning.

Each reason points to a next step: verify the email, find a direct address, try the phone, ask the deal owner, or leave the person alone.
