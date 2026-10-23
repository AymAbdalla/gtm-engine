# gtm-engine

[![tests](https://github.com/AymAbdalla/gtm-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/AymAbdalla/gtm-engine/actions/workflows/tests.yml)

Ten GTM engineering skills for Claude Code and Codex, packaged as the `aym-gtm` plugin. They cover outbound from start to finish: who to sell to, which data is safe to use, who has a reason to hear from you now, who goes into a play, what to say, what to do today, how the book and the CRM stay in step, whether any of it works, and what to automate first.

Every skill reads and writes plain files (CSV, JSON, Markdown) in one workspace folder, and works with any CRM, sequencer or data vendor. Nothing sends a message, enrolls anyone or writes to a live system. A script does the checking and a person makes every decision that can't be undone.

## Install

Claude Code:

```
/plugin marketplace add AymAbdalla/gtm-engine
/plugin install aym-gtm@gtm-engine
```

Codex:

```
codex plugin marketplace add AymAbdalla/gtm-engine
```

Then install `aym-gtm` from the Codex plugin list. Run a skill directly with `/aym-gtm:daily-plan` (Claude Code) or `$daily-plan` (Codex).

## The ten skills, in the order they run

| Skill | The question it answers |
| --- | --- |
| `icp-define` | Who should we sell to? Writes the ICP as testable rules and sorts every account in, out or unknown, with one reason each. |
| `data-quality` | Who on this list can we actually contact? Cleans a list into five buckets, verifies before outreach, audits a CRM export. |
| `signal-score` | Who has a real reason to hear from us now? Scores dated buying signals and writes one sourced why-now line per account. |
| `account-book` | What is the one record of every account and person? Merges sources, keeps your edits, gates each channel, picks one strategy per account. |
| `play-build` | Who goes into this play, and why? Proposes an enrollment list with every drop counted and explained. |
| `outreach-draft` | What do we say, and is it true? Drafts messages and checks every number, name and claim against its source. |
| `daily-plan` | What do I do today, and did it all get done? Plans the day in each prospect's calling hours and closes it with nothing unlogged. |
| `crm-sync` | How do the book and the CRM stay in step? Compares both with their last agreed values and writes a plan a person applies. |
| `funnel-review` | Is any of this working, and how sure are we? Rates with counts and 95% ranges, pre-registered tests, at most three actions. |
| `motion-map` | What should we automate first? Checks a map of the sales motion and picks one step to move up one automation level. |

Each skill folder has a `SKILL.md`, reference files, its scripts and a made-up example workspace you can run.

## How the skills share one system

- One ICP-fit rule (`scripts/gtm_fit.py`), copied byte for byte into the four skills that judge fit, so an account can't fit in one step and fail in the next. A blank field means "enrich first", never "out".
- Open deals flow from the CRM export through the account book to the play and the day plan, so outreach stops at any account with a live deal.
- Do-not-contact always wins, on every channel, in every skill that picks people or writes to them.

## Why each skill works the way it does

[docs/design-records/](docs/design-records/) has one record per skill: the problem, the choices made and the alternatives turned down, what was tested, and what was fixed after review.

## Results

- **Pressure tests (Oct 21, 2026).** Each skill was run by separate helper sessions on five kinds of case: a normal request, an ambiguous one, a broken input, a missing tool and a request it should not take. The helpers were not fully isolated from the session running them, so this is a strong check, not an outside one. 49 of 50 cases passed. The failure was `play-build` choosing a daily cap and dates itself on an ambiguous request instead of asking. Four more skills (`daily-plan`, `crm-sync`, `funnel-review`, `motion-map`) passed while assuming a default instead of asking, and `signal-score` once marked an account playable on research interest alone.
- **Quality review and fixes (Oct 22, 2026).** A skill-by-skill review led to one shared ICP-fit rule and to open deals being protected end to end, plus smaller fixes, including all of the findings above. An independent review then found seven more problems, and those were fixed too. Five reruns of the affected cases passed.
- **Tests.** 365 unit tests cover the scripts, the rules shared across skills and each example workspace.

## Tests

From the repository root, with Python 3 (checked with 3.13):

```
python3 -m unittest discover -s tests -p "test_gtm_*.py"
```

## License

MIT. See [LICENSE](LICENSE).
