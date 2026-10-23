# Eligibility funnel: signal-oct

Play type: signal. Every drop is counted with its reason.

| Step | Rule | Removed | Left |
|---|---|---|---|
| 0 | Everyone in the book | | 20 |
| 1 | Account is in this play's scope | 8 | 12 |
| 2 | Account strategy allows outbound | 1 | 11 |
| 3 | Account is yours to work | 1 | 10 |
| 4 | No stop status, opt-out, left tag or stop outcome in the log | 1 | 9 |
| 5 | Not in a conversation from the last 30 days | 0 | 9 |
| 6 | Not already in a live sequence | 0 | 9 |
| 7 | Passes the email gate from the book | 1 | 8 |
| 8 | Is a buyer (has a persona) | 0 | 8 |
| 9 | Not touched in the last 14 days | 1 | 7 |
| 10 | Not removed by you | 0 | 7 |
| 11 | Seat choice, at most 1 per account | 3 | 4 |
| 12 | Fits the calendar (2 a day, one per account a day) | 0 | 4 |

Proposed: 4.
Check: 20 in the book minus 16 removed (adds count as negative) equals 4 proposed. The counts add up.

## Reasons

**1. Account is in this play's scope**
- 6: account: no playable signal
- 2: account: signal not playable: only context signals

**2. Account strategy allows outbound**
- 1: account status live_deal

**3. Account is yours to work**
- 1: owned by jordan

**4. No stop status, opt-out, left tag or stop outcome in the log**
- 1: status do_not_contact

**7. Passes the email gate from the book**
- 1: email gate: catch-all domain

**9. Not touched in the last 14 days**
- 1: touched 2026-10-14, within 14 days

**11. Seat choice, at most 1 per account**
- 2: account cap: 1 per account
- 1: not the seat this signal points to
