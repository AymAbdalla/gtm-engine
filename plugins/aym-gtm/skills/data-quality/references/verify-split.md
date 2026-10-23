# Verify, then split

`verify_split.py` joins a verification file onto a list and writes `safe.csv` and `held.csv`. Each row gains `verify_channel, verify_verdict, verify_score, verify_reason`.

## The verification file

The user exports it from their own verification or enrichment vendor. Columns: `person_id, email, channel, verdict, score` (extra columns are fine). `channel` is `email`, `phone` or `linkedin`. Rows match by `person_id`; rows with no `person_id` match by email. Never by name.

## Which channel

`--channel email|call|linkedin`. Without it, the script reads the list's file name ("email", "call", "dial", "phone", "linkedin"). If the name is unclear it uses **call**, the strictest channel, and says so.

## Fail closed

A person is held when any of these is true:

- their status is in `stop_statuses`, a tag is in `dnc_tags`, `left_tags`, or `channel_block_tags` for this channel (bounced for email; dnc_phone and phone_failed for calls), or their notes ask not to be contacted
- there is no result for the channel's source (`email` for email, `phone` for call)
- the only results are for another channel. An email result never clears a call.
- two results disagree (one says valid, one says invalid)
- the verdict is not in `verify.ok_verdicts` (catch_all, risky, unknown...)
- for email, the result is for a different address than the one on the list
- the channel needs a score and the score is missing or below `verify.min_score_by_channel`

Only rows that clear every check go to `safe.csv`. Set a channel's minimum score to `null` when the vendor gives no score for it (often LinkedIn).

## What to tell the user

Safe vs held counts, the top held reasons and what would clear them (re-verify, find a direct number, confirm the address). Held is not "bad". It is "not proven yet".
