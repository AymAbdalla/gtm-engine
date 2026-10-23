#!/usr/bin/env python3
"""Audit a CRM export, score its health and write fix tickets. Read only.

  audit    reads accounts.csv, people.csv and an optional sequences.csv,
           writes audit.md, audit.json, fixes.csv and review-queue.csv
  recheck  compares fixes.csv with a fresh export and splits it into
           fixes-ready.csv (still current), fixes-skip.csv (already done)
           and fixes-drift.csv (changed since the plan: do not submit)

Nothing here writes to a CRM. Tickets are proposals you submit yourself.
"""
import argparse
import csv
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtm_fit import fit as icp_fit  # noqa: E402  (shared ICP-fit rule, copied in four skills)

DEFAULTS = {
    "icp": {
        "size": {"min": 200, "max": 2000},
        "countries": [],
        "industries_in": [],
        "industries_out": [],
        "exclude_relationships": ["competitor", "customer", "partner", "parent_decides"],
    },
    "freemail_domains": ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                         "icloud.com", "aol.com", "proton.me", "protonmail.com"],
    "stop_statuses": ["hold", "booked", "not_interested", "wrong_person", "left",
                      "do_not_contact", "archived"],
    "dnc_tags": ["opted_out", "dnc_all"],
    "left_tags": ["moved"],
    "channel_block_tags": {"email": ["bounced"], "call": ["dnc_phone", "phone_failed"], "linkedin": []},
    "clean": {"dnc_note_patterns": ["do not contact", "don't contact", "not to contact",
                                    "unsubscribe", "remove me", "stop emailing"]},
    "audit": {
        "overdue_days": 21,
        "stale_tags": ["this_week", "call_today"],
        "stale_days": 14,
        "out_of_icp_status": "hold",
        "domain_min_people": 3,
        "domain_min_share": 0.6,
        "weights": {"suppression_in_notes": 3, "bounce_still_usable": 3, "sequences": 3,
                    "out_of_icp_active": 2, "duplicate_accounts": 2, "domain_mismatch": 2,
                    "no_channel": 2, "empty_accounts": 1, "stale_flags": 1},
    },
}
LEGAL = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "gmbh", "limited", "lp", "llp"}
FIX_COLUMNS = ["ticket_id", "step", "record_type", "record_id", "field", "current_value",
               "new_value", "evidence", "check_first", "verify"]
REVIEW_COLUMNS = ["item", "record_type", "record_id", "issue", "evidence"]
STEPS = {
    1: "Stops: record do-not-contact and close sequences to stopped, opted-out or dead people",
    2: "Suppression fields: mark bounced emails invalid",
    3: "Exclusions: take out-of-ICP accounts off active",
    4: "Bounce triage: sort real bounces from mis-logged call outcomes",
    5: "Sequences: close overdue enrollments, then re-enter past repliers by hand",
    6: "Records: merge duplicate accounts, fix account domains, clear stale flags",
    7: "Enrichment last: find people and channels for what is left",
}


def deep_merge(base, extra):
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path):
    data = {}
    if path and Path(path).exists():
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    return deep_merge(DEFAULTS, data)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return [dict(r) for r in reader]


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def tags_of(row):
    return [t.strip() for t in (row.get("tags") or "").split(";") if t.strip()]


def norm_domain(value):
    d = (value or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    return d.split("/")[0]


def norm_company(name):
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    return " ".join(w for w in words if w not in LEGAL)


def to_int(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def health(results):
    """100 x (1 - sum(w * sqrt(share)) / sum(w)) over the checks that ran."""
    ran = [r for r in results if r["ran"]]
    total = sum(r["weight"] for r in ran)
    if not total:
        return 100.0
    loss = sum(r["weight"] * math.sqrt(r["share"]) for r in ran)
    return round(100 * (1 - loss / total), 1)


def grade(score):
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def icp_reasons(account, icp):
    """Known reasons an account is outside the ICP (the shared fit rule). Blank fields
    are unknown, not out, so they never become a ticket here."""
    verdict, reason = icp_fit(account, icp)
    return [reason] if verdict == "out" else []


class Audit:
    def __init__(self, cfg, accounts, people, sequences, today):
        self.cfg, self.a = cfg, cfg["audit"]
        self.accounts, self.people, self.sequences = accounts, people, sequences
        self.today = today
        self.fixes, self.review, self.results = [], [], []
        self.stop = [x.lower() for x in cfg["stop_statuses"]]
        self.dnc_tags = [x.lower() for x in cfg["dnc_tags"]]
        self.left_tags = [x.lower() for x in cfg.get("left_tags", [])]
        self.email_block = [x.lower() for x in cfg["channel_block_tags"].get("email", [])]
        self.phrases = [x.lower() for x in cfg["clean"]["dnc_note_patterns"]]
        self.open_people = [p for p in people
                            if (p.get("status") or "").strip().lower() not in self.stop]

    def dnc_reason(self, person):
        """Do-not-contact recorded somewhere other than the status field."""
        hit = [t for t in tags_of(person) if t.lower() in self.dnc_tags]
        if hit:
            return f"tag {hit[0]}"
        notes = (person.get("notes") or "").lower()
        phrase = next((x for x in self.phrases if x in notes), "")
        if phrase:
            return f"notes say '{phrase}'"
        return ""

    def left_reason(self, person):
        """A tag that says the person may have left the company (not an opt-out)."""
        hit = [t for t in tags_of(person) if t.lower() in self.left_tags]
        return f"tag {hit[0]}" if hit else ""

    def fix(self, step, rtype, rid, field, current, new, evidence, check_first):
        shown = f"'{new}'" if new else "empty"
        self.fixes.append({"step": step, "record_type": rtype, "record_id": rid, "field": field,
                           "current_value": current, "new_value": new, "evidence": evidence,
                           "check_first": check_first,
                           "verify": f"a fresh export shows {field} {shown} for {rtype} {rid}; "
                                     "recheck lists it as already done"})

    def queue(self, rtype, rid, issue, evidence):
        self.review.append({"record_type": rtype, "record_id": rid, "issue": issue, "evidence": evidence})

    def result(self, cid, title, step, affected, denominator, ran=True, note=""):
        share = (affected / denominator) if denominator else 0.0
        self.results.append({"id": cid, "title": title, "step": step, "weight": self.a["weights"].get(cid, 1),
                             "affected": affected, "denominator": denominator,
                             "share": round(min(share, 1.0), 4), "ran": ran, "note": note})

    def check_suppression_in_notes(self):
        hits = 0
        for p in self.open_people:
            why = self.dnc_reason(p)
            left = self.left_reason(p)
            if why:
                hits += 1
                self.fix(1, "person", p["person_id"], "status", p.get("status", ""), "do_not_contact",
                         f"{why} but status is still {p.get('status', '') or 'blank'}; "
                         "do-not-contact must be the status field, not a note or tag",
                         "confirm it is the person's own request")
            elif left:
                hits += 1
                self.fix(1, "person", p["person_id"], "status", p.get("status", ""), "left",
                         f"{left} says the person may have left, but status is still "
                         f"{p.get('status', '') or 'blank'}",
                         "confirm they left the company; this is not an opt-out")
        self.result("suppression_in_notes", "Do-not-contact only in notes or tags, status still open", 1,
                    hits, len(self.open_people))

    def check_bounces(self):
        hits = 0
        for p in self.open_people:
            if not any(t.lower() in self.email_block for t in tags_of(p)):
                continue
            hits += 1
            if not (p.get("email") or "").strip():
                self.queue("person", p["person_id"], "bounce tag but no email",
                           "likely a call outcome logged as a bounce; fix the tag, not the email")
            elif (p.get("email_status") or "").strip().lower() != "invalid":
                self.fix(2, "person", p["person_id"], "email_status", p.get("email_status", ""), "invalid",
                         f"tagged bounced; {p.get('email', '')} still marked usable",
                         "confirm the bounce came from this address")
        self.result("bounce_still_usable", "Bounced people still marked usable", 2, hits, len(self.open_people))

    def check_out_of_icp(self):
        active = [a for a in self.accounts if (a.get("status") or "").strip().lower() == "active"]
        hits = 0
        for acc in active:
            reasons = icp_reasons(acc, self.cfg["icp"])
            if reasons:
                hits += 1
                self.fix(3, "account", acc["account_id"], "status", acc.get("status", ""),
                         self.a["out_of_icp_status"], "; ".join(reasons),
                         "confirm no live deal or owner exception")
        self.result("out_of_icp_active", "Out-of-ICP accounts still active", 3, hits, len(active))

    def check_sequences(self):
        if self.sequences is None:
            self.result("sequences", "Sequence problems", 5, 0, 0, ran=False, note="no sequences file given")
            return
        people = {p.get("person_id", ""): p for p in self.people}
        active = [s for s in self.sequences if (s.get("status") or "").strip().lower() == "active"]
        per_person = {}
        for s in active:
            per_person.setdefault(s.get("person_id", ""), []).append(s)
        bad = set()
        for s in active:
            pid = s.get("person_id", "")
            rid = f"{pid}:{s.get('sequence', '')}"
            person = people.get(pid, {})
            status = (person.get("status") or "").strip().lower()
            tags = [t.lower() for t in tags_of(person)]
            dnc = self.dnc_reason(person)
            if status in self.stop:
                why = f"person status {status}"
            elif dnc:
                why = f"do-not-contact: {dnc}"
            elif self.left_reason(person):
                why = f"person may have left: {self.left_reason(person)}"
            elif any(t in self.email_block for t in tags):
                why = "mailbox bounced"
            elif (person.get("email_status") or "").strip().lower() == "invalid":
                why = "email invalid"
            else:
                why = ""
            due = parse_date(s.get("due_date"))
            if why:
                bad.add(rid)
                self.fix(1, "sequence", rid, "status", "active", "closed", why,
                         "close before the next step sends")
            elif due and (self.today - due).days > self.a["overdue_days"]:
                bad.add(rid)
                evidence = f"step {s.get('step', '')} due {due.isoformat()}, {(self.today - due).days} days overdue"
                self.fix(5, "sequence", rid, "status", "active", "closed", evidence,
                         "check no reply arrived since the export")
                if "replied" in tags:
                    self.queue("person", pid, "re-entry candidate",
                               "past replier in an overdue sequence; re-enter by hand with a fresh angle")
        for pid, rows in per_person.items():
            if len(rows) > 1:
                names = ", ".join(sorted(r.get("sequence", "") for r in rows))
                for r in rows:
                    bad.add(f"{pid}:{r.get('sequence', '')}")
                self.queue("person", pid, "enrolled in more than one active sequence", names)
        self.result("sequences", "Sequence problems (dead mailbox, overdue, double)", 5, len(bad), len(active))

    def check_duplicates(self):
        by_domain, by_name = {}, {}
        for acc in self.accounts:
            d = norm_domain(acc.get("domain"))
            if d:
                by_domain.setdefault(d, []).append(acc["account_id"])
            n = norm_company(acc.get("name"))
            if n:
                by_name.setdefault(n, []).append(acc)
        dup = set()
        for d, ids in sorted(by_domain.items()):
            if len(ids) > 1:
                dup.update(ids)
                self.queue("account", ";".join(ids), "safe merge (same domain)", d)
        for n, accs in sorted(by_name.items()):
            ids = [a["account_id"] for a in accs]
            domains = {norm_domain(a.get("domain")) for a in accs}
            if len(ids) > 1 and len(domains) > 1:
                dup.update(ids)
                self.queue("account", ";".join(ids), "possible duplicate (similar name, different domain)",
                           ", ".join(sorted(domains)))
        self.result("duplicate_accounts", "Duplicate accounts", 6, len(dup), len(self.accounts))

    def check_domains(self):
        by_account = {}
        for p in self.open_people:
            by_account.setdefault(p.get("account_id", ""), []).append(p)
        hits = 0
        for acc in self.accounts:
            own = {norm_domain(acc.get("domain"))} | {norm_domain(d) for d in (acc.get("other_domains") or "").split(";")}
            own.discard("")
            work = []
            for p in by_account.get(acc["account_id"], []):
                email = (p.get("email") or "").strip().lower()
                d = email.split("@")[-1] if "@" in email else ""
                if d and d not in self.cfg["freemail_domains"]:
                    work.append((p, d))
            off = [(p, d) for p, d in work if d not in own]
            if not off:
                continue
            counts = {}
            for _, d in off:
                counts[d] = counts.get(d, 0) + 1
            top, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if n >= self.a["domain_min_people"] and n / len(work) >= self.a["domain_min_share"]:
                hits += n
                self.fix(6, "account", acc["account_id"], "domain", acc.get("domain", ""), top,
                         f"{n} of {len(work)} work emails use {top}; the account domain is likely wrong",
                         "open the company site and confirm the domain")
            else:
                for p, d in off:
                    hits += 1
                    self.queue("person", p["person_id"], "email domain not on the account",
                               f"{d} vs {', '.join(sorted(own)) or 'no domain'}")
        self.result("domain_mismatch", "Email domain differs from the account", 6, hits, len(self.open_people))

    def check_stale_flags(self):
        hits = 0
        stale = [t.lower() for t in self.a["stale_tags"]]
        for p in self.open_people:
            tags = tags_of(p)
            flagged = [t for t in tags if t.lower() in stale]
            touched = parse_date(p.get("last_touch_date"))
            if flagged and (touched is None or (self.today - touched).days > self.a["stale_days"]):
                hits += 1
                keep = ";".join(t for t in tags if t.lower() not in stale)
                self.fix(6, "person", p["person_id"], "tags", p.get("tags", ""), keep,
                         f"{', '.join(flagged)} set but last touch {touched or 'never'}",
                         "confirm the flag is not for this week")
        self.result("stale_flags", "Stale short-term flags", 6, hits, len(self.open_people))

    def check_enrichment(self):
        active = [a for a in self.accounts if (a.get("status") or "").strip().lower() == "active"]
        with_people = {p.get("account_id", "") for p in self.open_people}
        empty = [a["account_id"] for a in active if a["account_id"] not in with_people]
        self.result("empty_accounts", "Active accounts with no people", 7, len(empty), len(active),
                    note=", ".join(empty))
        none = [p["person_id"] for p in self.open_people
                if not (p.get("email") or "").strip() and not (p.get("phone") or "").strip()]
        self.result("no_channel", "People with no email and no phone", 7, len(none), len(self.open_people),
                    note=", ".join(none))

    def run(self):
        for check in (self.check_suppression_in_notes, self.check_bounces, self.check_out_of_icp,
                      self.check_sequences, self.check_duplicates, self.check_domains,
                      self.check_stale_flags, self.check_enrichment):
            check()
        self.fixes.sort(key=lambda f: (f["step"], f["record_type"], f["record_id"], f["field"]))
        for i, f in enumerate(self.fixes, 1):
            f["ticket_id"] = f"T{i:03d}"
        for i, r in enumerate(self.review, 1):
            r["item"] = f"R{i:03d}"
        score = health(self.results)
        counts = {"accounts": len(self.accounts), "people": len(self.people),
                  "open_people": len(self.open_people),
                  "stopped_people": len(self.people) - len(self.open_people),
                  "sequences": None if self.sequences is None else len(self.sequences)}
        stops = sum(1 for f in self.fixes if f["step"] == 1)
        return {"date": self.today.isoformat(), "health": score, "grade": grade(score),
                "counts": counts, "blockers": stops,
                "checks": self.results, "fix_count": len(self.fixes), "review_count": len(self.review)}


def render(summary, fixes, review):
    c = summary["counts"]
    ran = [r for r in summary["checks"] if r["ran"]]
    skipped = [r for r in summary["checks"] if not r["ran"]]
    seq = ("no sequences file, so sequence checks did not run" if c["sequences"] is None
           else f"{c['sequences']} sequence rows")
    lines = [f"# CRM audit ({summary['date']})", "",
             "## Scope and limits", "",
             f"- Read: {c['accounts']} accounts, {c['people']} people and {seq}.",
             f"- Checked: {c['open_people']} open people. Skipped: {c['stopped_people']} people whose status "
             "already stops contact.",
             f"- Checks run: {len(ran)} of {len(summary['checks'])}."
             + (" Not run: " + "; ".join(f"{r['title']} ({r['note']})" for r in skipped) + "." if skipped else ""),
             "- Not covered: anything newer than this export, whether emails really deliver (use verify mode), "
             "and any data outside these files.", "",
             "## Verdict", ""]
    if summary["blockers"]:
        lines.append(f"Blockers found within scope: {summary['blockers']} stop tickets (step 1). "
                     "Handle them before any other fix or any outreach.")
    else:
        lines.append("No blockers found within scope. This is not a pass: it covers only the files and "
                     "checks listed above.")
    lines += ["",
              f"Health: **{summary['health']} ({summary['grade']})**. "
              "Score = 100 x (1 - sum of weight x square root of share, divided by total weight). "
              "Weights are editable defaults in gtm.json.", "",
              "| Check | Affected | Of | Share | Weight |", "|---|---|---|---|---|"]
    for r in summary["checks"]:
        if r["ran"]:
            lines.append(f"| {r['title']} | {r['affected']} | {r['denominator']} | {r['share']:.0%} | {r['weight']} |")
        else:
            lines.append(f"| {r['title']} | not run | | | {r['weight']} ({r['note']}) |")
    found = [r for r in ran if r["affected"]]
    lines += ["", "## Findings", ""]
    if not found:
        lines.append("None of the checks that ran found a problem.")
    for r in found:
        lines += [f"### {r['title']}", "",
                  f"- Evidence: {r['affected']} of {r['denominator']} ({r['share']:.0%})."
                  + (f" Records: {r['note']}." if r["note"] else ""),
                  f"- Fix: step {r['step']} of the fix plan below. Ticketed rows are in fixes.csv; "
                  "anything a person must decide is in review-queue.csv.",
                  "- Verify: after the fixes, export again and rerun the audit. This check should show 0 affected. "
                  "Each ticket also has its own verify line in fixes.csv.", ""]
    lines += ["## Fix plan, in order", ""]
    for step, text in STEPS.items():
        n_fix = sum(1 for f in fixes if f["step"] == step)
        extra = ""
        if step == 7:
            notes = [r for r in summary["checks"] if r["id"] in ("empty_accounts", "no_channel") and r["affected"]]
            extra = "; ".join(f"{r['title'].lower()}: {r['note']}" for r in notes)
        lines.append(f"{step}. {text}. Tickets: {n_fix}." + (f" {extra}" if extra else ""))
    lines += ["", f"Review queue: {len(review)} items in review-queue.csv. Never ticket these: "
              "a person decides merges, unclear domains and double enrollments.", "",
              "Before submitting fixes.csv, export again and run `audit_crm.py recheck`. "
              "Submit only rows that land in fixes-ready.csv.", "",
              "Nothing was changed in any system. This is a read-only report."]
    return "\n".join(lines) + "\n"


def recheck(fixes, accounts, people, sequences):
    tables = {"account": {a.get("account_id", ""): a for a in accounts},
              "person": {p.get("person_id", ""): p for p in people},
              "sequence": {f"{s.get('person_id', '')}:{s.get('sequence', '')}": s for s in (sequences or [])}}
    ready, skip, drift = [], [], []
    for f in fixes:
        record = tables.get(f.get("record_type", ""), {}).get(f.get("record_id", ""))
        row = dict(f)
        if record is None:
            row["recheck"] = "record not found in the fresh export"
            drift.append(row)
            continue
        now = record.get(f.get("field", ""), "")
        if now == f.get("new_value", ""):
            row["recheck"] = "already done"
            skip.append(row)
        elif now == f.get("current_value", ""):
            row["recheck"] = "still current: safe to submit"
            ready.append(row)
        else:
            row["recheck"] = f"changed since the plan: now '{now}'"
            drift.append(row)
    return ready, skip, drift


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("audit", "recheck"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", default="gtm")
        p.add_argument("--config")
        p.add_argument("--accounts")
        p.add_argument("--people")
        p.add_argument("--sequences", help="CSV: person_id, sequence, step, due_date, status")
        p.add_argument("--out")
        if name == "audit":
            p.add_argument("--today")
        else:
            p.add_argument("--fixes", required=True)
    args = parser.parse_args(argv)
    ws = Path(args.workspace)
    accounts = read_csv(args.accounts or ws / "input" / "accounts.csv")
    people = read_csv(args.people or ws / "input" / "people.csv")
    sequences = read_csv(args.sequences) if args.sequences else None
    out_dir = Path(args.out or ws / "clean" / "audit")
    inputs = {Path(p).resolve() for p in (args.accounts or ws / "input" / "accounts.csv",
                                           args.people or ws / "input" / "people.csv",
                                           args.sequences, getattr(args, "fixes", None)) if p}
    if out_dir.resolve() in {p.parent for p in inputs}:
        raise SystemExit("refusing to write into the input folder; choose another --out")
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.cmd == "recheck":
        fixes = read_csv(args.fixes)
        names = ("fixes-ready.csv", "fixes-skip.csv", "fixes-drift.csv")
        if any((out_dir / n).resolve() in inputs for n in names):
            raise SystemExit("refusing to overwrite an input file; choose another --out")
        groups = recheck(fixes, accounts, people, sequences)
        for name, rows in zip(names, groups):
            write_csv(out_dir / name, FIX_COLUMNS + ["recheck"], rows)
        print(f"ready {len(groups[0])}  skip {len(groups[1])}  drift {len(groups[2])}  -> {out_dir}")
        return 0
    names = ("fixes.csv", "review-queue.csv", "audit.md", "audit.json")
    if any((out_dir / n).resolve() in inputs for n in names):
        raise SystemExit("refusing to overwrite an input file; choose another --out")
    cfg = load_config(args.config or ws / "gtm.json")
    today = date.fromisoformat(args.today) if args.today else date.today()
    audit = Audit(cfg, accounts, people, sequences, today)
    summary = audit.run()
    write_csv(out_dir / "fixes.csv", FIX_COLUMNS, audit.fixes)
    write_csv(out_dir / "review-queue.csv", REVIEW_COLUMNS, audit.review)
    text = render(summary, audit.fixes, audit.review)
    (out_dir / "audit.md").write_text(text, encoding="utf-8")
    (out_dir / "audit.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
