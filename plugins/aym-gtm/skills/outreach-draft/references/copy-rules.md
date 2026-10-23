# Copy rules

These rules keep messages short, true and easy to answer. Every number and limit is a default in `gtm.json` under `copy`. Change them there; they are starting points, not standards.

| Rule | Default | Why | Checked by script |
| --- | --- | --- | --- |
| Word band | 25 to 60 words; fail above 85 | Short messages get read on a phone. | Yes (note outside the band, fail above the hard limit) |
| One question | exactly 1 | One clear ask is easy to answer. Two asks get none. | Yes |
| End on the question | on | The reply button sits right under the ask. | Yes |
| No dash punctuation | em dash, en dash and ` -- ` | Reads like a template. Use a period or comma. | Yes (`em_dash`) |
| No exclamation points | on | Sounds like a pitch. | Yes (`exclamation`) |
| No links | on | Links hurt delivery and look like marketing. | Yes (`links`) |
| No gendered pronouns | optional | You often do not know how a third person refers to themselves. | Yes when `gendered_pronouns` is in `banned` |
| Banned phrases | "just checking in", "circle back", "touch base", "hope this finds you well" | Filler that says nothing. Add competitor names here too. | Yes |
| One proof line at most | 1 | One true number beats a list of claims. | Yes |
| Proof is VERIFIED, has a source and is allowed for the persona | on | A claim must have a current source and fit the reader. | Yes |
| Every number is backed | on | A number must appear in the proof line used or the sourced fact. Spelled-out numbers count too (`copy.number_words`: two, three, half, double...). A hyphenated word is not a number ("two-minute"), and `copy.number_ok_phrases` (first half, second half) are skipped. | Yes |
| No hint of research interest | `copy.intent_words` (researching, been looking into, visited our...; a plain "worth looking into" is fine) | Prospects should never learn you watched their research. | Yes (fail) |
| Seller claims need proof | `copy.claim_phrases` (teams like yours, our customers, we help...) | A claim about results with no `proof:` field may be made up. | Yes (needs a human) |
| Facts match the cited source | `copy.fact_words` (raised, funding, named, hired...) | A fact in the body that the `why_now` line does not state may be wrong. | Yes (needs a human) |
| The greeting names the right person | on | "Hi Sarah" to Dana loses the deal in one word. A short form is fine ("Rob" for Robert, "Bob" and a few other common nicknames), accents are ignored (José = Jose), and "Hi there" or "Hi team" is not checked. | Yes, against the draft heading |
| The person is cleared to contact | `book/people.csv` when it exists | A draft for someone blocked or opted out must never be sent. | Yes (fail) |
| First touch has a sourced, dated fact | on | "Why you, why now" must be true and checkable. | Yes (`why_now`, `source`, `source_date`) |
| Subjects | new email thread needs one; replies have none | Replies stay in the same thread. | Yes |
| Subject follows the same rules | dashes, exclamation points, links, banned phrases and unbacked numbers | The subject is the first thing read. | Yes |
| LinkedIn connect note | 300 characters | The platform limit for a note. | Yes |
| Only declared variables | on | An unknown `{{variable}}` would go out blank. | Yes, in templates |
| Unfilled variable means needs human | on | A draft with a gap cannot be sent. | Yes |
| Angle tag on every draft | on | Lets you compare angles later. | Yes |

## Writing guidance the script cannot check

- Open with them, not you. The first line is about their company or role.
- Write like a person: plain words, short sentences, no buzzwords.
- One idea per message. Cut anything that does not support the ask.
- Make the ask small: a yes or no question beats "15 minutes this week".
- The fact you cite should connect to the problem you solve. If you cannot connect them in one sentence, pick another fact or say "weak case".
- Do not mention topic intent data, tracking or how you found the signal. The checker catches common phrases; it cannot catch every way of saying it.
- Follow-ups add something new: a different angle, a smaller ask, or a clean close. Never "bumping this".

## Call drafts

Call drafts are a call reason plus one opening question. The script checks banned items, proof and numbers, but not the word band.
