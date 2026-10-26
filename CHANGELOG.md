# Changelog

## 0.6.1 (2026-10-26)

- Each skill ends a substantial run (files you'll rely on, send from or share) by giving you one line to paste into a fresh chat, or the other tool, that checks the output against its brief and sources, report only. A helper the working chat starts gives only a "helper review", and the chat's own look is "self-review"; neither counts as an independent check.
- `SECURITY.md` says how to report a security problem privately.

## 0.6.0 (2026-10-23)

- First release as its own repository. Until now, `aym-gtm` shipped inside the agent-skills collection (0.4.0-rc.1 to 0.5.0); it now has its own version.
- One shared ICP-fit rule across `icp-define`, `data-quality`, `account-book` and `signal-score`: a blank field means "enrich first", and any known reason to be out wins.
- Open deals are protected from the CRM export through `account-book` to `play-build` and `daily-plan`. A manual strategy override can no longer reopen a live deal, and a partial opportunities export can no longer turn one back to active.
- `outreach-draft` checks numbers, research hints, seller claims, the facts in the body and the greeting against the sources, and checks the book's gate.
- `funnel-review` counts meetings booked from earlier touches, groups people by first-touch week, and compares a play with its holdout.
- `play-build` stops when a setting that decides who gets contacted is missing, and its optional holdout counts the same unit as the worked side.
- `motion-map` marks the automation pick provisional while the map has a flow problem, and treats a stage that writes to a sending tool as one that can't be undone.
- Design records for all ten skills are now part of the repository.
