---
name: icp-define
description: Define who a company should sell to and save it as a testable gtm.json plus a one-page icp.md. Interviews the user or reads their notes, checks the config with a script, sorts accounts in, out or unknown with one reason each, checks the ICP against won deals, and sizes segments as estimates. Use for "define our ICP", "who should we target", "set up gtm.json", "size this market" or "which segments". Not for cleaning lists (data-quality), scoring signals (signal-score), building the book (account-book) or writing outreach (outreach-draft).
---

# ICP define

Turn what the user knows about their best buyers into one config file every other aym-gtm skill reads, plus a short page a person can read. The config is a hypothesis to test, not a fact. Every number in it is an editable default.

## If the script cannot run

This skill's results come from `scripts/icp_check.py`. If you cannot run them (no shell, no Python, or the script stops with an error), stop and say so plainly. Do not write the `icp/` check outputs, and do not call the config valid by hand, do not work out the results by applying the script's rules yourself, and never copy the example outputs in `assets/`. Writing `gtm.json` and `icp.md` from the interview is still your job; say they are unchecked. Give the user the command to run when they can: `python3 <skill-dir>/scripts/icp_check.py --workspace <workspace> --out <workspace>/icp`.

## Ground rules

- Use made-up data or data the user is allowed to use in this environment. Keep employer or customer data where it is allowed to live.
- Never buy data, call a data vendor, find contacts or contact anyone. This skill writes files only.
- A claim about the market needs a named source. A guess is labeled "hypothesis".
- Write plain English. No em dashes.

## Inputs

- The user's answers, notes, a won-deals or customer list, or an existing `gtm.json` to revise.
- Optional: an accounts CSV (`<workspace>/input/accounts.csv`, columns in [config reference](references/config.md#accounts-columns)).
- Optional: a won deals CSV (`<workspace>/input/won-deals.csv`, the same columns, or just `account_id`).
- Optional: market counts per segment, each with the source it came from.

The workspace defaults to `./gtm`. Ask the user where it lives if no folder is named and `./gtm` does not exist.

## Steps

1. **Gather.** If `gtm.json` exists, read it and revise only what the user wants changed. Otherwise use the [interview guide](references/interview.md). Ask only for what is missing. Ask one question at a time. For each answer, note where it came from: won deals, the customer list, or the user's judgment.
2. **Write `gtm.json`.** Start from [the example](assets/example/gtm.json). Keep the section names, because other skills read them. The [config reference](references/config.md) says which skill reads which section and what each field means.
   - The interview fills `seller`, `icp`, `personas`, `not_buyer_titles`, `review_titles`, `region_title_rule`, `segments` and `signals`. Replace every value in those.
   - The other sections (`clean`, `send_gate`, `copy`, `daily`, `play`, `sync` and the rest) keep the example's values as editable defaults. Say so in `icp.md`, and name the skill that will use each one.
   - Set `icp.review_by` to a date, usually a quarter out, when the ICP should be checked again.
   - Size band: a floor, a ceiling and a sweet spot inside it. The sweet spot is where won deals cluster, not the whole band.
   - Exclusions: competitors, current customers, partners, and accounts where a parent company decides. Excluded industries go in `industries_out`.
   - Tech stack (optional): tools that make an account a fit go in `icp.technographics.required_any`, tools that rule it out in `excluded`. They match an accounts `tech` column.
   - Personas: an ordered list. The first pattern that matches wins, so put the most specific titles first. Each persona has a lane (finance, tech, ops and so on) and a role (decision maker, champion, influencer, technical gatekeeper).
   - Not-buyer titles go to quarantine. Review titles (consultant, advisor, founder) go to a person only when no persona matched.
   - Region rule: a title that names another region (EMEA, APAC) marks the person out of region, unless the title is senior or global.
   - Segments: an industry group plus a size range. Keep it to 2 to 5.
3. **Write `icp.md`.** One page: who we sell to, who we do not, the personas, the segments and why, and what is still a hypothesis. Use [the example](assets/example/icp.md) as the shape.
4. **Check.** Run `python3 <skill-dir>/scripts/icp_check.py --workspace <workspace> --out <workspace>/icp`, where `<skill-dir>` is this skill's folder. List every config error with the fix you propose, edit `gtm.json` only after the user agrees, then rerun. Warnings are fine when the user accepts them.
5. **Sort the list.** When an accounts CSV exists, the check writes `accounts-icp.csv` with `in_icp` (yes, no or unknown), one plain `icp_reason`, `size_band`, `segment`, `account_points` and `points_detail` (each part of the score, so the user can check and change the weights). A blank country, industry, headcount or tech field is unknown, which means "enrich first", not "out"; any known reason to be out still wins. data-quality, account-book and signal-score use the same rule (`scripts/gtm_fit.py`). Account status (hold, live deal) does not change fit.
6. **Check against won deals.** When `input/won-deals.csv` exists, the check reports what share of won deals falls inside the ICP and names the ones outside, and lists any it cannot judge as unknown. A low share means the ICP describes a hope, not the buyers: revisit it with the user before scaling outbound.
7. **Size the market.** Follow the [market sizing guide](references/market-size.md). Use only counts the user supplied with a source. Review about 25 sample rows per segment and record how many do not fit; the script lowers the count by that share. Report each segment to two significant figures with its band (too narrow, tight, sweet spot, healthy, too broad). Always say "estimate, not forecast".
8. **Report** (see below) and stop.

## Outputs

- `<workspace>/gtm.json` and `<workspace>/icp.md`
- `<workspace>/icp/accounts-icp.csv` and `<workspace>/icp/icp-check.md` when an accounts list exists

## Boundaries

- This skill does not enrich, find people, score signals, clean lists or draft messages. Name the right aym-gtm skill instead.
- It does not decide for the user. When the evidence is thin, it writes the choice as a hypothesis and names the test that would settle it.
- It never overwrites an input file. Revising `gtm.json` means editing the user's file in place only after they agree to the change.

## Report

Tell the user, in plain words:

- Files written, with paths.
- Accounts in, out and unknown, and the top three reasons for "out".
- Won deals inside the ICP ("7 of 10"), and the ones outside with their reason, or "no won deals file".
- Any "review the ICP" warning (the `icp.review_by` date has passed).
- Each segment's estimate, band and source, or "no count source yet".
- What is still a hypothesis and the cheapest way to test it.
- What the skill did not do: no data bought, no contacts found, nothing sent.
