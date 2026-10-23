# Clean a list

`clean_list.py` reads people and accounts and puts every person in one of five files. Each row keeps all its input columns and gains `account_name, persona, lane, role, phone_type, channels, defects, score, score_detail, reason`. `score_detail` lists each part of the score so a person can check it.

## The order of checks

The first check that fires decides the file. Order matters: safety first, then fit, then quality.

0. **Do-not-contact wins first.** Before duplicates are judged, the script links rows that share a `person_id`, an email, or the same normalized name at the same account, and looks for stops on any of them:
   - **Do-not-contact** (status do_not_contact, an opt-out tag in `dnc_tags`, or a note phrase in `clean.dnc_note_patterns`): every linked row goes to `quarantine.csv` with "linked record P10 is do-not-contact (...)".
   - **Left** (status left, or a tag in `left_tags` such as moved): every linked row goes to `quarantine.csv` with "linked record P10: person status is left".
   - **Any other stop status** on a linked row (booked, hold and so on): the other rows go to `review.csv`, because the stale row may be the wrong one. Check which record is current.
   A duplicate row can never carry a do-not-contact or departed person into `ready.csv`.
1. **Duplicates and joins** go to `review.csv`:
   - same `person_id` or same email as an earlier row: "duplicate of P06"
   - same first and last name at the same account, different email: "possible duplicate"
   - same phone number (last 10 digits) and last name at the same account: "possible duplicate (same phone and last name)", which catches Rob and Robert
   - `account_id` not found in the accounts file
2. **Screens** go to `quarantine.csv`:
   - person `status` in `stop_statuses` (hold, booked, not_interested, wrong_person, left, do_not_contact, archived)
   - an opt-out tag in `dnc_tags` (opted_out, dnc_all) or a left tag in `left_tags` (moved: the person may have left, which is not an opt-out)
   - notes that say "do not contact", "unsubscribe" or similar. The reason tells the user to record it as a field, because a note does not stop a sequencer.
   - account out of ICP, from the shared fit rule (`scripts/gtm_fit.py`): below the size floor, above the ceiling, country outside, industry excluded or not listed, tech stack ruled out, a relationship in `icp.exclude_relationships` (competitor, customer, partner, parent_decides), or archived. A blank field is not a reason to be out.
   - person country outside the ICP countries
3. **The title ladder**:
   - No title: `enrich.csv` (find it before scoring).
   - A hard not-buyer title (intern, student, recruiter, sales rep): quarantine. This beats a persona match, so "Accounts Payable Intern" is out.
   - Persona patterns are tried in the order listed in `gtm.json`; the first match wins.
   - A persona matched but the account's fit is unknown (a blank country, industry, headcount or tech field): `enrich.csv`, "account fit unknown". Fill the field before anyone is contacted.
   - No persona, but a soft title (consultant, advisor, founder): review. A soft title only matters when no persona matched.
   - No persona and no soft title: quarantine.
   - A title naming another region (EMEA, APAC, Europe...) is out of region unless the title is senior (chief, VP, head of). "Finance Director, EMEA" is out; "VP Finance, Europe" stays.
4. **Channels and defects** (the person matched a persona):
   - Phone type: `direct`, `switchboard` (a round number ending in 00), `toll_free`, `international` (outside `home_country_codes`), `malformed`, `none`. The format rules assume a +1 home market. Set `clean.home_country_codes` for others and check a sample.
   - Defects: `dnc_phone` (a tag in `channel_block_tags.call`), `phone_international`, `phone_toll_free`, `phone_malformed`, `email_invalid`, `email_bounced` (a tag in `channel_block_tags.email`), `catch_all_email`, `personal_email` (a domain in the top-level `freemail_domains`), `email_domain_mismatch` (not on the account's domain or other_domains), `profile_mismatch` (the profile URL does not contain the last name; first-name nicknames are fine; links that carry an id instead of a name, such as Sales Navigator lead links or a member id like `/in/ACwAA...` or `/in/ACoAA...` (case-sensitive, so a name slug such as `acosta-maria` is still checked), are not checked), `stale_touch` (last touch older than `clean.stale_touch_days`), `vendor_no_record`.
   - Identity doubt (personal email, domain mismatch, profile mismatch) goes to `enrich.csv`. Confirm who the person is before anyone contacts them.
   - No usable channel (no good email, no direct or switchboard phone that is not do-not-call): `enrich.csv`.
   - Otherwise: ready.

## The score

```
score = phone points (0 if the phone is do-not-call)
      + persona points x persona_multiplier
      + size points (sweet spot or in band)
      + never-touched bonus
      - defect_penalty x number of defects (not counting dnc_phone)
      - dnc_phone_penalty if the phone is do-not-call
```

Phone type is the biggest factor, because the list is built for calling first. If the user works email first, lower `phone_points` and say so.

## Ranking and the per-account cap

- `ready.csv` is sorted by score, highest first, ties by person_id. Only the top `clean.cap_per_account` people per account stay; the rest go to `later.csv` with "over the per-account cap". A cap keeps one account from eating the day.
- `enrich.csv` is sorted by account value (tier points plus a sweet-spot bonus), then score, so fixing data starts where it pays most.
- `review.csv` and `quarantine.csv` are sorted by account, then person.

## What to tell the user

- The counts per file and the top reasons in `report.md`.
- Any rule that looks wrong for their data, with the `gtm.json` key that controls it.
- That quarantine is not deletion. It is a list with reasons that a person can overrule.
