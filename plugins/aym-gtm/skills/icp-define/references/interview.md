# ICP interview guide

Ask only what the user has not already told you. One question at a time. Offer a default from the example config when the user is unsure, and mark it "hypothesis".

For each answer, record its basis:

- **evidence**: won deals, the customer list, or a report the user can point to
- **judgment**: the user's experience, no data behind it
- **default**: taken from the example, not checked

## 1. The offer

- What do you sell, in one sentence, and to which team?
- What problem does it fix that the buyer feels every week?

## 2. Best customers

- Name 5 to 10 customers who bought fast, stayed and grew. What do they have in common: size, industry, country, systems they use, how they grew?
- Can you export recent won deals? Saved as `input/won-deals.csv`, the check measures how many fall inside the ICP.
- Which deals did you lose or regret? What was different about them?

Use the answers to set the sweet spot. The sweet spot is where the good customers cluster. The wider band is where a deal is still possible.

## 3. Firmographics

- Headcount: the smallest and largest company you can serve, and the range where you win most.
- Countries or regions you can sell to and support.
- Industries that buy well. Industries you never sell to, and why.
- Systems: tools your best customers run that make the deal easier, and tools that rule an account out. These become `icp.technographics` (optional).

## 4. Exclusions

- Competitors, current customers, partners and resellers. Their records get `relationship` set so every skill skips them.
- Accounts where a parent company makes the decision: exclude, or route to whoever owns the parent.

## 5. Personas

For each buyer type:

- the title words that identify them (these become `title_patterns`)
- their lane (finance, tech, ops, sales and so on)
- their role in the deal: decision maker, champion, influencer or technical gatekeeper
- how much they matter (`points`)

Then:

- **Not-buyer titles**: titles that can never buy (interns, recruiters, sales reps). These go to quarantine.
- **Review titles**: titles that might matter (consultant, founder). A person reviews these when no persona matched.
- **Region words**: words in a title that point to another region (EMEA, APAC). Senior or global titles are exempt.

Put the most specific patterns first. The first match wins.

## 6. Buying triggers

- What events make a good account more likely to buy now? Examples: a new finance leader, a leader leaving, hiring for a related role, funding, rapid growth, research activity on the topic.
- How long does each trigger stay useful?

These fill the `signals` section that signal-score reads.

## 7. Segments

Group the ICP into 2 to 5 segments, each an industry group plus a size range, that would get a different message. For each segment, ask whether the user has a count of matching companies and where it came from. No source means no count.

## Close

Read back the ICP in five lines and ask the user to confirm or correct it before writing the files. Agree a review date (`icp.review_by`), usually a quarter out.
