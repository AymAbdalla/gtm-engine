# Scoring, expiry and the playable gate

Every number here is a default in `gtm.json` under `signals`. Change them to fit your market, then keep them stable long enough to learn from the results.

## Signal types (defaults)

| Type | Weight | Expires after | Seat to contact | Why it matters |
| --- | --- | --- | --- | --- |
| `new_leader` | 5 | 180 days | the named new leader | New leaders review tools and spend in their first months. |
| `leader_gap` | 4 | 180 days | the most senior remaining leader, never the person who left | Someone is covering two jobs and looking for help. |
| `hiring` | 4 | 60 days | the likely manager of the open role | A job post names a problem the team is paying to solve. Most roles are filled within weeks. |
| `funding` | 4 | 365 days | decision maker | New money, new plans, new budget. |
| `topic_intent` | 3 | 30 days | decision maker | Timing only. Never mention it, and never playable on its own. |
| `growth` | 2 | 180 days | decision maker | New sites, offices or teams add process strain. |
| `layoffs` | 0 | 180 days | context only | Context for tone. Never a reason to reach out. |

Add your own type by adding a key under `signals.types` with `weight`, `expires_days`, `seat` and `watch` (the phrase used when suggesting what to watch for). A row with a type that is not in the config is skipped and reported.

A hiring signal for a role your product does not touch is noise. Either leave it out of the raw file or give it a lower weight with its own type, for example `hiring_other` at 2.

## Recency

Age is `today - event_date` in days. The recency table is a list of `[max_age_days, factor]`, checked in order:

```json
"recency": [[30, 1.0], [90, 0.7], [100000, 0.4]]
```

So a 30-day-old signal keeps its full weight, a 31-day-old one gets 0.7, and anything past 90 days gets 0.4 until it expires.

A signal is expired when its age is greater than its type's `expires_days`. Expired rows stay in `signals.csv` with status `expired` so you can see them, but they never score.

## Account score

1. For each live signal: value = weight x recency factor.
2. For each signal type at the account, keep only the best value.
3. Score = the sum of those best values, rounded to 2 places.

Worked example (today is 2026-10-20):

- New CFO named 2026-09-28: age 22, factor 1.0, value 5 x 1.0 = 5.0
- AP job posted 2026-08-31: age 50, factor 0.7, value 4 x 0.7 = 2.8 (a job post older than 60 days would have expired)
- Score = 5.0 + 2.8 = **7.8**

A second job post at the same account would not add to the score, because only the best hiring value counts. This keeps one noisy careers page from outranking a real leadership change.

## Matching signals to accounts

1. Clean the signal's domain (drop `https://`, `www.` and any path) and look it up in each account's `domain` and `other_domains`.
2. If there is no domain match, compare the company name after lowercasing, removing punctuation and dropping legal endings at the end (inc, llc, ltd, corp, co, company, plc and similar). It must match exactly.
3. If a domain or name fits more than one account, the row is reported as unmatched with that reason. Fix the duplicate accounts first.
4. No fuzzy matching. A wrong match puts the wrong fact in front of the wrong person.

5. When a signal matches by domain but the company name in the signal differs from your account's name (after removing legal endings), the match stands but the row gets a `check` note: confirm it is the same company before you use it.

## Duplicates and corrected pulls

A signal is identified by its `signal_id`, or by company, type, date and source when there is no id. Raw pulls are never edited. To correct a row, save the fixed row with the same `signal_id` in a new dated folder under `signals/raw/`.

- The newest pull folder wins. Older copies of the same signal are marked `duplicate` with the reason "replaced by the newer pull".
- Within one pull, the first copy wins and later copies are `duplicate`.
- A skipped row (no source, no valid date, unknown type) never blocks another row. A later corrected row with the same id scores normally, and a skipped correction never replaces a good older row.

## The playable gate

An account with live signals is playable only when:

- `status` is not in `blocked_status` (default: hold, live_deal, archived)
- `relationship` is not blocked. The blocked list is `signals.blocked_relationships` when set, otherwise `icp.exclude_relationships`, otherwise competitor, customer and partner. `parent_decides` is always blocked.
- the account fits the ICP by the shared fit rule (`scripts/gtm_fit.py`): out lists the reason, a blank field lists "fit unknown: enrich first"
- at least one live signal has a weight above 0 and is not timing-only. When the only live signals are timing-only (default `topic_intent`), `why_not` is "intent only: find a citable reason first"

If any check fails, `playable` is `no` and `why_not` lists every reason. Held accounts still show their score and signals so you can see what you are waiting on.

## Fit by timing (`quadrant`)

| Fit | Citable live signal | Quadrant | What to do |
| --- | --- | --- | --- |
| in | yes | act | work it if the gate allows |
| in | no | nurture | watch for a signal |
| out or unknown | yes | verify | check the fit before any touch |
| out or unknown | no | suppress | leave it |

Status (hold, live deal) is separate from the quadrant: it only decides `playable`.

## What the why-now line uses

- The best live signal that has a weight above 0 and is not timing-only (default timing-only types: `topic_intent`). Ties go to the newer event, then the lower signal id.
- If the only live signals are timing-only, the line says to use them as timing only and to find a citable reason first.
- If nothing live is left, the line says "weak case: nothing dated to point to" and names the strongest signal type to watch for.

## Reading the trace

`signals/signals.csv` keeps every raw row with `status`, `reason`, `account_id`, `age_days`, `weight`, `recency` and `value`. When a score looks wrong, filter this file by account id. The answer is always in a row.
