# Example: a rebuild that keeps your edits

Everything here is made up. Ledgerline is a fictional company selling spend-management software to finance teams. Domains end in `.example`, and phone numbers use the fictional 555-01xx range.

## What is in the folder

- `gtm.json`: the shared Ledgerline config (the same file as in icp-define), including personas, the send gate, the size floor, book sources, area-code time zones and a top list of 3.
- `input/accounts.csv`: 10 accounts, including a competitor, a parent-decides account, one below the size floor and one with a live deal.
- `input/researched.csv`: a researched list with no ids. It has better titles and phones for a few people.
- `input/people.csv`: the CRM export.
- `input/crm-snapshot.csv`: what the CRM holds today.
- `signals/scored.csv`: one playable signal and one context-only signal.
- `book/`: a book built on 2026-10-12, then edited by hand. The edits are:
  - Marcus's title was changed in the book.
  - A note was typed in `new_note`.
  - Ezra was set to booked, with a next step.
  - Simone's time zone was typed in.
  - Rowan was added by hand.
  - Ironleaf Freight was tagged `lost_deal`.
  - Riverbend Components got a strategy override and a pain line.

Since then the CRM changed:
- Marcus's title changed in the CRM too.
- Hollis has a new phone.
- Nadia opted out.
- Aiko was added.

## Run it on a copy

```bash
cp -r <skill-dir>/assets/example /tmp/gtm-demo
python3 <skill-dir>/scripts/build_book.py --workspace /tmp/gtm-demo --today 2026-10-20 --export A01,A02
python3 <skill-dir>/scripts/rank_accounts.py --workspace /tmp/gtm-demo --today 2026-10-20
```

## What you should see

- Marcus keeps the title you typed. The CRM's new title is ignored, and `fixes.csv` asks the CRM to take yours.
- Hollis gets the new phone, because nobody edited it in the book.
- Your note is now in Marcus's `notes` as `2026-10-20: ...`, and `new_note` is empty.
- Ezra stays booked, with the next step kept.
- Nadia becomes do_not_contact, because the opt-out beats everything.
- Simone's time zone stays and is marked `manual`.
- Rowan stays, marked `manual`.
- Aiko joins the book.
- Strategies:
  - Spendwise Labs: excluded (competitor).
  - Quarry Peak Health: hold (parent decides).
  - Tallgrass Software: hold (below the size floor).
  - Coastal Ledger Partners: live.
  - Ironleaf Freight: re-engage.
  - Maplecrest Clinics: signal.
  - Riverbend Components: priority (your override).
  - Northpine Logistics and Brightmill Manufacturing: priority (tier).
  - Ashford Advisory: automated.
- The export for A01 and A02 holds 3 people. Priya (risky email), Tessa (catch-all) and Jonah (a sales rep, not a buyer) are left out, with reasons.
- Run the build a second time: every edit above is still there.
- The top list of 3 is frozen on the first run. A second run reports challengers instead of reshuffling.
