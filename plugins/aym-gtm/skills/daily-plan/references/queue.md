# The extra-touch queue

Sequence steps are the committed work. The queue fills the rest of the day with people who are not in a sequence: inbound leads nobody called, warm contacts, and the best of the rest.

## Who is eligible

A person in `book/people.csv` is a candidate when all of these hold. Each drop is counted in the plan under "Left out of extra touches".

- not in a sequence and not in an approved enrollment
- status not in `stop_statuses`, and no tag in `dnc_tags` or `left_tags`
- no log outcome of `opt_out`, `not_interested`, `wrong_person` or `left`, at any time
- the account is yours: its `owner` is blank or matches `daily.owner` (else `play.owner`, else `you`), the same rule play-build uses
- the account's own `status` is not `live_deal`, `hold` or `archived`, whatever the book's strategy says
- nobody at the account has replied, shown interest or booked in the last `daily.reply_lookback_days` days (a person handles that account). The account comes from the book
- last touch at least `daily.min_days_between_touches` days ago (log and the book's `last_touch_date`)
- a usable channel: a call (`call_ok` = yes and a phone), or LinkedIn (`linkedin_ok` = yes and a profile) when there is no phone and no email path. LinkedIn sequence steps use the same `linkedin_ok` check. A book built before `linkedin_ok` existed gets the same person and account checks here instead: stop status, opt-out or left tags, do-not-contact notes, not-buyer titles, an excluded relationship, and a held, excluded or live-deal account. Nobody blocked on email or calls for who they are or where they work is ever moved to LinkedIn.

Then at most `daily.extras_per_account` per account and `daily.max_extra_cards` per day.

## Who gets the slots

The slots go to the best candidates, not to whichever block is shown first. Candidates are ranked by: a card with a prep line before one without, then a call before LinkedIn (a callable buyer always beats a LinkedIn-only person at the same account), then the score (or the fact ladder when scores are flat). Only after the slots are filled are the cards grouped into blocks for display.

## Blocks, in this order (display only)

1. **inbound**: a tag in `daily.inbound_tags` and never touched. Speed matters most here.
2. **warm**: a tag in `daily.warm_tags`.
3. **linkedin_only**: no phone and no email path, but a profile.
4. **volume**: everyone else.

Sequence steps sit between inbound and warm in the plan.

## The score

Each candidate gets seven sub-scores from 0 to 1. The score is their weighted average, with weights from `daily.weights`. Every card shows its score with the parts behind it (each sub-score and its weight), so you can see which input moved it and change a weight in `gtm.json` instead of guessing.

| Sub-score | 1.0 when | Notes |
| --- | --- | --- |
| signal | the account has the top playable signal | scaled by the account's signal score over the best one |
| seat | decision maker | champion 0.8, influencer 0.5, technical gatekeeper 0.4, other 0.2 |
| recency | last touch inside `daily.recency_peak_days` | never touched gets `daily.never_touched_recency`; too recent is 0; older fades to 0.3; unknown is 0 |
| fit | account tier P1 | P2 0.7, P3 0.4, other 0.3 |
| due_step | the book's `next_step` starts with a date on or before today | else 0 |
| single_threaded | exactly one other person at the account is in a sequence | a second thread helps |
| deliverability | verified email at or above the minimum score | risky or catch-all 0.3, phone only 0.5, nothing 0 |

## Flat-score guard

If the highest and lowest scores differ by less than `daily.flat_gap`, the scores carry no real signal. The plan says so, hides the scores, and orders each block by plain facts instead, in `daily.fact_ladder` order: inbound and untouched, never touched, buying role, seniority from the title, then newest. A ranking that looks precise but is not is worse than an honest one.

## No prep line, no dial

Every extra card needs a one-line reason to reach out: the account's why-now line from signal-score, the book's `next_step` text, or the last line of the person's notes. A card with none is marked `no_prep` and sinks to the bottom of its block. Find a real reason, or skip it.
