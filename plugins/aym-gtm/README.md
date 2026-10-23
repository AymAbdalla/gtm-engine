# aym-gtm

GTM engineering skills for one person or a small outbound team. Each skill does one job, reads and writes plain files (CSV, JSON, Markdown) in one workspace folder, and works with any CRM, sequencer or data vendor. Nothing here sends a message, enrolls anyone or writes to a live system. You review the files and act.

## Install

Claude Code:

```
/plugin marketplace add AymAbdalla/gtm-engine
/plugin install aym-gtm@gtm-engine
```

On Claude Code 2.1.275 or later, one line also works: `/plugin install aym-gtm --marketplace AymAbdalla/gtm-engine`.

Codex:

```
codex plugin marketplace add AymAbdalla/gtm-engine
```

Then install `aym-gtm` from the Codex plugin list.

## The ten skills

| Skill | What it does |
| --- | --- |
| `icp-define` | Writes your ideal customer profile as a testable `gtm.json` plus a plain `icp.md`: size band, countries, industries, excluded relationships, buyer personas, segments and market size estimates, checked against your won deals. Every number is an editable default. |
| `data-quality` | Cleans a people list into ready, review, enrich and quarantine files with a reason for each person; splits a list by vendor verification results; audits a CRM export and writes fix tickets. Do-not-contact always wins. |
| `signal-score` | Scores dated buying signals (new leaders, hiring, funding and more) by weight and age, decides which accounts are playable (fit and a citable reason, never intent alone), and writes one sourced "why now" line per account. |
| `account-book` | Builds the prospect book (one row per person) and the account book (one row per account). Your edits survive every rebuild. Adds the send gate, follow-up gate, readiness, buying-group lanes, a strategy per account and a sticky top-accounts list. |
| `play-build` | Designs and fills one play (signal, event, reactivation, multithread or blitz): who qualifies with a counted reason for every drop, who at each account, daily caps, start dates and stop rules. Proposes enrollments for you to approve, with an optional holdout to measure the play. |
| `outreach-draft` | Drafts emails and LinkedIn notes into a dated file with a `sent` checkbox, then checks every draft against your copy rules and proof registry. You send by hand. |
| `daily-plan` | Turns approved enrollments, sequences and your activity log into today's cards and call blocks by time zone, then closes the day so every planned touch is done, skipped with a reason, or flagged. |
| `crm-sync` | Compares the book and a fresh CRM export, decides which side wins field by field, and writes change plans for both sides. Blanks never erase values, nothing is dropped silently, and a short export stops the run. Open deals in the CRM stop outbound at that account. It never touches the CRM. |
| `funnel-review` | Reports what is working with honest numbers: rates with sample sizes and ranges, segment rates on the right base, why meetings moved (volume, rate, mix), meetings by first-touch week, opener and message tests, play holdouts, and a quota model. Ends with up to three actions. |
| `motion-map` | Maps a sales motion stage by stage, checks the map for gaps, decides who owns each decision, and picks the one step to automate first, with a loop check before anything runs on a schedule. |

## Workspace

```
gtm/
  gtm.json                 shared settings (icp-define writes it; every skill reads its own section)
  icp.md                   the ICP in plain words
  input/                   accounts.csv, people.csv, optional crm-snapshot.csv, events.csv, crm-export/ (you supply)
  clean/                   data-quality outputs
  signals/raw/YYYY-MM-DD/  raw signal pulls (you supply; never edited)
  signals/                 signal-score outputs
  book/                    account-book outputs
  plays/<play_id>/         play-build outputs; you mark approved rows
  outreach/                proof.json, sequences.json, drafts/, lint report
  log/activity.csv         every touch and outcome, appended
  plan/                    daily-plan cards and day closes
  sync/                    crm-sync change plans and state
  funnel/                  funnel-review reports, tests and targets
  motion/                  motion-map map and checks
```

## Order

icp-define, data-quality, signal-score, account-book, play-build, outreach-draft, then each day daily-plan and crm-sync, and each week funnel-review. Use motion-map when you design or change the process. Each skill can also run alone on its own inputs.

## Examples

Each skill ships a small example workspace under `skills/<skill>/assets/example/`. All of it is made up: a fictional seller, fictional companies on `.example` domains, and fictional people with 555 phone numbers.

## License

MIT. See `LICENSE`.
