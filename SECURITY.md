# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue, so nobody can use them before a fix is out.

Use GitHub's private reporting: [report a vulnerability](https://github.com/AymAbdalla/gtm-engine/security/advisories/new) (Security tab → Report a vulnerability).

Include what you found, where (file and line, or the skill and the request that triggers it), and the steps to reproduce it. Please don't include real secrets or personal data in the report.

## What's covered

The aym-gtm plugin, its scripts and its tests, on the latest commit of `main`. Older versions are not patched; update to the latest instead.

Skills and scripts here run inside an AI agent on the user's machine, so reports about these are in scope too: a skill that can be tricked by text in a file or web page into running commands, leaking data or skipping a confirmation step.

## What to expect

A reply within 7 days, a fix or a decision within 30 days for confirmed problems, and credit in the changelog if you'd like it.
