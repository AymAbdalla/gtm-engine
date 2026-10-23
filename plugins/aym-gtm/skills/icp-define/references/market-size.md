# Market sizing guide

The goal is an honest count of companies that fit each segment, labeled as an estimate. It is not a revenue forecast.

## 1. Get a count with a source

The count comes from a source the user can name: a public business register, an industry association list, a list the user built, or a data tool the user is allowed to use. Put it in the segment as `market_count`, with `market_count_source`. The check script refuses a count with no source.

When no count exists, say so. The script then reports only how many accounts from the user's own list fall in each segment.

## 2. Check for missing data before trusting a filter

When adding one filter (for example revenue or funding) cuts the count by more than 90 percent, treat that as a gap in the source data, not a real drop. Use the count without that filter and say why.

## 3. Check the noise

Look at about 25 sample companies from the count, starting with the largest. Count how many do not really fit: wrong industry, a holding company, a closed business, a duplicate. Record it in the segment:

```json
"noise_check": {"reviewed": 25, "noisy": 3}
```

The script lowers the count by that share: estimate = count × (1 − noisy ÷ reviewed).

## 4. Read the band

The script rounds each estimate to two significant figures and gives it a band from `market_bands`:

| Band | Default range | What it usually means |
|---|---|---|
| too narrow | under 250 | Not enough companies to run a steady outbound motion. Widen the size or industry. |
| tight | 250 to 999 | Workable for an account-based approach. Every account counts. |
| sweet spot | 1,000 to 4,999 | Room to test messages without burning the market. |
| healthy | 5,000 to 50,000 | Plenty of room. Split it into sharper segments. |
| too broad | over 50,000 | The segment is not a segment yet. Add a filter. |

These ranges are defaults, not standards. Change them in `gtm.json` when the user's sales motion is different.

## 5. Optional: serviceable revenue

When the user gives an average contract value (`seller.average_contract_value`) and a share of each segment they can realistically serve (`addressable_share` on the segment), the script multiplies them out. Always call the result "hypothesis, not forecast".

## What not to claim

- Do not present a count without its source.
- Do not turn an estimate into a revenue promise.
- Do not compare segments sized from different sources as if they were equal.
