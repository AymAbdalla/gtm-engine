#!/usr/bin/env python3
"""Plan a two-way sync between the GTM book and a CRM export, through files only.

Reads book/people.csv (and book/accounts.csv), a fresh CRM export in
input/crm-export/ (people.csv, optional accounts.csv, activity.csv,
bounces.csv), log/activity.csv and the last run's sync/state.json.
Writes plan files under sync/. It never contacts a CRM or any other system.

Rungs: `plan` (default) writes the plan files. `copy` also applies the CRM
plan to a copy of the export under sync/copy/ so a person can review the
result. A live write is never done by this script.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FIELDS = ["first_name", "last_name", "title", "email", "phone", "linkedin_url", "country", "status"]

DEFAULT_SYNC = {
    "fields": FIELDS,
    "account_fields": ["name", "domain", "employees", "industry", "country", "tier"],
    "field_map": {f: f for f in FIELDS},
    "account_field_map": {f: f for f in ["name", "domain", "employees", "industry", "country", "tier"]},
    "crm_columns": {"id": "crm_id", "updated_at": "updated_at", "account_domain": "account_domain",
                    "account_name": "account_name", "email_status": "email_status",
                    "activity_external_id": "external_id", "person_id": "crm_id"},
    "row_floor_share": 0.8,
    "pilot_rows": 3,
    "next_step_business_days": 3,
    "create_missing": True,
    "carry_forward_runs": 5,
    "channels": ["email", "call", "linkedin", "meeting"],
    "outcomes": ["sent", "connected", "no_answer", "voicemail", "bad_number", "gatekeeper", "replied",
                 "interested", "not_now", "not_interested", "booked", "bounced", "opt_out",
                 "wrong_person", "left"],
    "engaged_outcomes": ["replied", "interested", "not_now", "booked"],
    "status_from_outcome": {"booked": "booked", "not_interested": "not_interested",
                            "opt_out": "do_not_contact", "wrong_person": "wrong_person", "left": "left"},
    "stop_outcomes": ["not_interested", "opt_out", "wrong_person", "left", "bounced"],
    "bounce_crm_field": "email_status",
    "bounce_crm_value": "invalid",
    "holidays": [],
    # CRM status spelling -> book status. Matching ignores case, spaces, dashes and underscores.
    # Every book status maps to itself. A CRM value not listed goes to review, never into the book.
    "status_map": {"do not contact": "do_not_contact", "dnc": "do_not_contact", "unsubscribed": "do_not_contact",
                   "opted out": "do_not_contact", "on hold": "hold", "meeting booked": "booked",
                   "not interested": "not_interested", "wrong person": "wrong_person",
                   "left company": "left", "no longer at company": "left"},
    # Book status -> the spelling to write in the CRM. Blank means the same word.
    "status_to_crm": {},
}

BOOK_STATUSES = ["active", "nurture", "hold", "booked", "not_interested", "wrong_person", "left",
                 "do_not_contact", "archived"]
PLAN_FILES = ["to-crm.csv", "to-book.csv", "to-book-reasons.csv", "to-book-accounts.csv", "to-log.csv",
              "conflicts.csv", "review.csv", "cadence.csv", "report.md"]
ACCT_UPDATE_COLS = ["account_id", "crm_id", "status", "owner", "relationship", "reason"]

PROTECTED = ("input", "log", "book", "signals", "outreach", "clean")
TO_CRM_COLS = ["row_id", "action", "object", "record_id", "field", "current_value", "new_value",
               "reason", "evidence", "pilot"]
REVIEW_COLS = ["review_id", "object", "record_id", "issue", "detail"]
CONFLICT_COLS = ["object", "record_id", "person_id", "field", "book_value", "crm_value", "baseline",
                 "book_time", "crm_time", "reason"]
REASON_COLS = ["person_id", "crm_id", "field", "book_value", "new_value", "reason"]
LOG_COLS = ["activity_id", "timestamp", "person_id", "account_id", "channel", "direction", "sequence",
            "step", "play_id", "angle", "opener", "outcome", "notes", "source"]
CADENCE_COLS = ["person_id", "account_id", "sequence", "last_step", "last_touch", "state", "reason",
                "next_due"]


# ---------------------------------------------------------------- helpers


def write_atomic(path, text):
    """Write a whole file or nothing: write a sibling temp file, then rename it over the target.
    An interrupted run leaves the old state, never half a file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def deep_merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return None, []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def file_hash(path):
    path = Path(path)
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_list(value):
    return [t.strip() for t in (value or "").split(";") if t.strip()]


def norm(value):
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def norm_name(value):
    return re.sub(r"[^a-z0-9 ]", "", norm(value))


def same(a, b, field=""):
    a, b = (a or "").strip(), (b or "").strip()
    if field in ("email", "domain"):
        return a.lower() == b.lower()
    if field in ("employees",):
        return a.replace(",", "") == b.replace(",", "")
    return a == b


def parse_ts(value, today):
    """Return (aware datetime or None, problem). A time after today is corrupt."""
    value = (value or "").strip()
    if not value:
        return None, ""
    try:
        if len(value) == 10:
            ts = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None, f"unreadable time {value!r}"
    # The latest moment of `today` anywhere on earth is today 23:59 at UTC-12.
    limit = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone(timedelta(hours=-12)))
    if ts > limit:
        return None, f"time {value} is after today"
    return ts, ""


def status_key(value):
    return re.sub(r"[\s_-]+", " ", (value or "").strip().lower()).strip()


def map_status(value, sync):
    """CRM status -> book status. Returns "" for blank and None for a value not on the map."""
    if not (value or "").strip():
        return ""
    table = {status_key(s): s for s in BOOK_STATUSES}
    table.update({status_key(k): v for k, v in (sync.get("status_map") or {}).items()})
    return table.get(status_key(value))


def status_for_crm(value, sync):
    return (sync.get("status_to_crm") or {}).get(value) or value


def fingerprint(workspace, exp):
    """One hash over every input this run reads. Same inputs, same plan."""
    h = hashlib.sha256()
    for path in [exp / "people.csv", exp / "accounts.csv", exp / "activity.csv", exp / "bounces.csv",
                 exp / "opportunities.csv",
                 workspace / "log/activity.csv", workspace / "book/people.csv", workspace / "book/accounts.csv",
                 workspace / "gtm.json"]:
        h.update(str(path.relative_to(workspace)).encode())
        h.update(file_hash(path).encode())
    return h.hexdigest()


def mark_stale(out):
    """Rename the last run's plan files so an old plan never sits beside a stopped run."""
    moved = []
    if not out.exists():
        return moved
    for name in PLAN_FILES:
        path = out / name
        if path.exists():
            stale = path.with_name(path.stem + ".stale" + path.suffix)
            path.replace(stale)
            moved.append(stale.name)
    return moved


def outcome_entry(outcome, ts, evidence, sync, rules, where):
    """The book change an outcome implies (status and tags), or None."""
    entry = None
    new_status = sync["status_from_outcome"].get(outcome)
    day = ts.date().isoformat()
    if new_status:
        entry = {"status": new_status, "tags": [], "since": day,
                 "reason": f"{outcome} logged {day}{where}", "evidence": evidence}
    if outcome == "opt_out" and rules["dnc_tags"]:
        entry = entry or {"status": "", "tags": [], "since": day, "reason": f"opted out{where}", "evidence": evidence}
        entry["tags"].append(rules["dnc_tags"][0])
    if outcome == "left" and rules["left_tags"]:
        entry = entry or {"status": "", "tags": [], "since": day, "reason": f"left{where}", "evidence": evidence}
        entry["tags"].append(rules["left_tags"][0])
    if entry:
        entry["runs"] = 0
    return entry


def add_business_days(start, n, holidays):
    d, left = start, n
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in holidays:
            left -= 1
    return d


def load_config(workspace):
    path = workspace / "gtm.json"
    cfg = {}
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    sync = deep_merge(DEFAULT_SYNC, cfg.get("sync", {}))
    if not sync.get("holidays") and isinstance(cfg.get("daily"), dict):
        sync["holidays"] = list(cfg["daily"].get("holidays", []))
    rules = {
        "stop_statuses": cfg.get("stop_statuses", ["hold", "booked", "not_interested", "wrong_person", "left",
                                                   "do_not_contact", "archived"]),
        "dnc_tags": cfg.get("dnc_tags", ["opted_out", "dnc_all"]),
        "left_tags": cfg.get("left_tags", ["moved"]),
    }
    return sync, rules


# ---------------------------------------------------------------- matching

class Matcher:
    """Book person lookup: CRM id, then email, then exact name at the same account. Never fuzzy."""

    def __init__(self, people, accounts):
        self.by_crm, self.by_email, self.by_name = {}, {}, {}
        self.last_candidates = []
        acct_keys = {}
        for a in accounts:
            keys = {norm_name(a.get("name"))}
            for d in [a.get("domain")] + split_list(a.get("other_domains")):
                if d:
                    keys.add(d.lower())
            acct_keys[a.get("account_id", "")] = keys - {""}
        self.acct_keys = acct_keys
        for p in people:
            if p.get("crm_id"):
                self.by_crm.setdefault(p["crm_id"], []).append(p)
            if p.get("email"):
                self.by_email.setdefault(p["email"].lower(), []).append(p)
            name = (norm_name(p.get("first_name")), norm_name(p.get("last_name")))
            if all(name):
                self.by_name.setdefault(name, []).append(p)

    def account_for(self, domain, name):
        domain, name = (domain or "").lower(), norm_name(name)
        hits = sorted(aid for aid, keys in self.acct_keys.items() if (domain and domain in keys) or (name and name in keys))
        return hits

    def match(self, row, cols):
        """Return (person or None, rung, problem)."""
        crm_id = row.get(cols["id"], "")
        if crm_id and crm_id in self.by_crm:
            hits = self.by_crm[crm_id]
            return (hits[0], "crm id", "") if len(hits) == 1 else (None, "", "two book people share this CRM id")
        email = row.get("email", "").lower()
        if email and email in self.by_email:
            hits = self.by_email[email]
            return (hits[0], "email", "") if len(hits) == 1 else (None, "", "two book people share this email")
        name = (norm_name(row.get("first_name")), norm_name(row.get("last_name")))
        if all(name) and name in self.by_name:
            accts = set(self.account_for(row.get(cols["account_domain"]), row.get(cols["account_name"])))
            hits = [p for p in self.by_name[name] if p.get("account_id") in accts]
            if len(hits) == 1:
                return hits[0], "name at account", ""
            if len(hits) > 1:
                self.last_candidates = [p.get("person_id", "") for p in hits]
                return None, "", f"{len(hits)} book people have this name at this account"
        return None, "", ""


# ---------------------------------------------------------------- core

class Plan:
    def __init__(self):
        self.to_crm, self.to_book, self.reasons = [], {}, []
        self.conflicts, self.review, self.to_log, self.notes = [], [], [], []
        self.needs_you = []

    def crm(self, action, obj, record_id, field, current, new, reason, evidence=""):
        self.to_crm.append({"action": action, "object": obj, "record_id": record_id, "field": field,
                            "current_value": current, "new_value": new, "reason": reason, "evidence": evidence})

    def book(self, person, field, new, reason):
        pid = person.get("person_id", "")
        row = self.to_book.setdefault(pid, {"person_id": pid, "account_id": person.get("account_id", ""),
                                            "crm_id": person.get("crm_id", "")})
        if field == "tags":
            tags = split_list(row.get("tags")) + [t for t in split_list(new) if t not in split_list(row.get("tags"))]
            row["tags"] = ";".join(tags)
        else:
            row[field] = new
        self.reasons.append({"person_id": pid, "crm_id": person.get("crm_id", ""), "field": field,
                             "book_value": person.get(field, ""), "new_value": new, "reason": reason})

    def flag(self, obj, record_id, issue, detail=""):
        self.review.append({"object": obj, "record_id": record_id, "issue": issue, "detail": detail})


def three_way(plan, obj, key, person, crm_row, fields, fmap, base, book_ts, crm_ts, crm_id_label, sync):
    """Compare one matched record field by field. Returns the agreed baseline values."""
    agreed = {}
    for f in fields:
        col = fmap.get(f, f)
        b, c = person.get(f, ""), crm_row.get(col, "")
        raw = c
        if f == "status":
            c = map_status(raw, sync)
            if c is None:
                plan.flag(obj, crm_id_label, "unknown CRM status",
                          f"{raw!r} is not in sync.status_map; add it there or fix it in the CRM. Nothing was changed.")
                continue
        prior = base.get(f)
        if same(b, c, f):
            agreed[f] = b
            continue
        if f == "status":
            out_b = status_for_crm(b, sync)
            if b == "do_not_contact":
                plan.crm("update", obj, crm_id_label, col, raw, out_b, "do-not-contact in the book always wins")
                continue
        if f == "status" and c == "do_not_contact":
            plan.book(person, f, c, "do-not-contact in the CRM always wins")
            continue
        new_b = status_for_crm(b, sync) if f == "status" else b
        if not c:
            plan.crm("update", obj, crm_id_label, col, raw, new_b, "CRM field is blank; a blank never clears the book")
            continue
        if not b:
            plan.book(person, f, c, "book field is blank; filled from the CRM")
            continue
        book_changed = prior is None or not same(b, prior, f)
        crm_changed = prior is None or not same(c, prior, f)
        if book_changed and not crm_changed:
            plan.crm("update", obj, crm_id_label, col, raw, new_b, "changed in the book since the last sync")
        elif crm_changed and not book_changed:
            plan.book(person, f, c, "changed in the CRM since the last sync")
        elif book_ts and crm_ts and book_ts != crm_ts:
            if book_ts > crm_ts:
                plan.crm("update", obj, crm_id_label, col, raw, new_b,
                         "both sides changed; the book change is newer", f"book {book_ts.isoformat()} > CRM {crm_ts.isoformat()}")
            else:
                plan.book(person, f, c, f"both sides changed; the CRM change is newer ({crm_ts.isoformat()})")
        else:
            why = "both sides changed and a time is missing, unreadable or after today" if prior is not None else \
                  "first sync, values differ and there is no time to say which is newer"
            plan.conflicts.append({"object": obj, "record_id": crm_id_label, "person_id": person.get("person_id", key), "field": f,
                                   "book_value": b, "crm_value": raw, "baseline": prior or "",
                                   "book_time": book_ts.isoformat() if book_ts else "",
                                   "crm_time": crm_ts.isoformat() if crm_ts else "", "reason": why})
    return agreed


def run(workspace, today, rung="plan", out=None, mapping_confirmed=False):
    workspace = Path(workspace).resolve()
    out = Path(out).resolve() if out else workspace / "sync"
    for name in PROTECTED:
        guard = (workspace / name).resolve()
        if out == guard or guard in out.parents:
            raise ValueError(f"refusing to write into {name}/: that folder holds inputs")
    if rung not in ("plan", "copy"):
        raise ValueError("this script only plans: use --rung plan or --rung copy. A live write is a person's action.")
    sync, rules = load_config(workspace)
    cols = sync["crm_columns"]
    fmap = sync["field_map"]
    holidays = set(sync.get("holidays", []))
    plan = Plan()

    _, people = read_csv(workspace / "book/people.csv")
    if not people and not (workspace / "book/people.csv").exists():
        mark_stale(out)
        raise ValueError("book/people.csv is missing: build the book with account-book first")
    _, accounts = read_csv(workspace / "book/accounts.csv")
    exp = workspace / "input/crm-export"
    exp_cols, crm_people = read_csv(exp / "people.csv")
    if exp_cols is None:
        mark_stale(out)
        raise ValueError("input/crm-export/people.csv is missing: export people from your CRM first")
    _, crm_accounts = read_csv(exp / "accounts.csv")
    _, opportunities = read_csv(exp / "opportunities.csv")
    _, crm_activity = read_csv(exp / "activity.csv")
    _, crm_bounces = read_csv(exp / "bounces.csv")
    log_cols, log_rows = read_csv(workspace / "log/activity.csv")

    state_path = out / "state.json"
    saved = json.loads(state_path.read_text(encoding="utf-8-sig")) if state_path.exists() else {}
    fp = fingerprint(workspace, exp)
    rerun = bool(saved.get("fingerprint")) and saved.get("fingerprint") == fp and "input_state" in saved
    # A rerun on the same inputs starts from the same state as the last run, so it gives the same plan.
    state = saved["input_state"] if rerun else {k: v for k, v in saved.items() if k not in ("fingerprint", "input_state")}
    watermark, wm_problem = parse_ts(state.get("watermark", ""), today)
    processed = set(state.get("processed_activity", []))
    legacy_watermark = "processed_activity" not in state
    baseline = state.get("baseline", {})
    pending = state.get("pending_bounces", {})
    prev_ids = set(state.get("export_ids", []))

    # Row floors: a short export would look like mass deletion.
    datasets = {"people": (exp / "people.csv", crm_people), "accounts": (exp / "accounts.csv", crm_accounts),
                "activity": (exp / "activity.csv", crm_activity), "bounces": (exp / "bounces.csv", crm_bounces),
                "opportunities": (exp / "opportunities.csv", opportunities)}
    ds_state, floor_trips, unchanged = {}, [], []
    for name, (path, rows) in datasets.items():
        if not path.exists():
            continue
        h = file_hash(path)
        prev = state.get("datasets", {}).get(name, {})
        ds_state[name] = {"hash": h, "rows": len(rows)}
        if prev.get("hash") == h:
            unchanged.append(name)
        if name in ("people", "accounts", "opportunities") and prev.get("rows"):
            floor = int(prev["rows"] * sync["row_floor_share"])
            if len(rows) < floor:
                floor_trips.append(f"{name}.csv has {len(rows)} rows; the last export had {prev['rows']} "
                                   f"(floor {floor}). A short export looks like mass deletion.")
    if floor_trips:
        stale = mark_stale(out)
        report = ["# CRM sync: stopped", "", "## Needs you", ""]
        report += [f"- {t} Export again and rerun. Nothing was planned." for t in floor_trips]
        report += ["", "No plan files were written and the sync state was not changed."]
        if stale:
            report += ["", "The last run's plan files were renamed so nobody applies an old plan by mistake: "
                       + ", ".join(f"`{n}`" for n in stale) + "."]
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        return {"stopped": True, "floor_trips": floor_trips, "stale": stale}

    matcher = Matcher(people, accounts)
    acct_by_id = {a.get("account_id", ""): a for a in accounts}
    new_baseline, new_pending = {}, {}
    seen_book, export_ids, held = set(), [], set()
    accounted = {"matched": 0, "new_in_crm": 0, "review": 0}
    person_by_crm = {}

    # ---- people: CRM export rows
    for row in crm_people:
        crm_id = row.get(cols["id"], "")
        if crm_id:
            export_ids.append(crm_id)
        matcher.last_candidates = []
        person, rung_used, problem = matcher.match(row, cols)
        if problem:
            held.update(matcher.last_candidates)
            detail = problem + (f": book people {', '.join(matcher.last_candidates)}" if matcher.last_candidates else "")
            plan.flag("person", crm_id or row.get("email", ""), "ambiguous match", detail)
            accounted["review"] += 1
            continue
        if person is None:
            accts = matcher.account_for(row.get(cols["account_domain"]), row.get(cols["account_name"]))
            if len(accts) != 1:
                why = "account not in the book" if not accts else "account matches two book accounts"
                plan.flag("person", crm_id or row.get("email", ""), "new in CRM, not brought in", why)
                accounted["review"] += 1
                continue
            new_row = {"person_id": "", "account_id": accts[0], "crm_id": crm_id}
            for f in sync["fields"]:
                new_row[f] = row.get(fmap.get(f, f), "")
            if "status" in new_row:
                mapped = map_status(new_row["status"], sync)
                if mapped is None:
                    plan.flag("person", crm_id or row.get("email", ""), "unknown CRM status",
                              f"{new_row['status']!r} is not in sync.status_map; the row is brought in with a blank status")
                    mapped = ""
                new_row["status"] = mapped
            key = "crm:" + (crm_id or row.get("email", "").lower())
            plan.to_book[key] = new_row
            plan.reasons.append({"person_id": "", "crm_id": crm_id, "field": "*new person*", "book_value": "",
                                 "new_value": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                                 "reason": "in the CRM, not in the book"})
            accounted["new_in_crm"] += 1
            continue
        pid = person.get("person_id", "")
        if pid in seen_book:
            plan.flag("person", crm_id, "two CRM rows match one book person", f"book person {pid}")
            accounted["review"] += 1
            continue
        seen_book.add(pid)
        accounted["matched"] += 1
        label = crm_id or person.get("crm_id", "")
        person_by_crm[label] = person
        if crm_id and not person.get("crm_id"):
            plan.book(person, "crm_id", crm_id, f"matched by {rung_used}; the book had no CRM id")
        key = label or pid
        book_ts, b_prob = parse_ts(person.get("updated_at", ""), today)
        crm_ts, c_prob = parse_ts(row.get(cols["updated_at"], ""), today)
        for prob, side in ((b_prob, "book"), (c_prob, "CRM")):
            if prob:
                plan.flag("person", key, f"{side} time ignored", prob)
        agreed = three_way(plan, "person", key, person, row, sync["fields"], fmap, baseline.get(key, {}),
                           book_ts, crm_ts, label, sync)
        merged = dict(baseline.get(key, {}))
        merged.update(agreed)
        new_baseline[key] = merged
        # The CRM shows the address as bounced. The book gets the bounced tag if it lacks it, whether
        # or not a bounce was waiting for this confirmation, so the tag is never lost.
        crm_bounced = any(norm(row.get(c)) == norm(sync["bounce_crm_value"])
                          for c in sorted({cols["email_status"], sync["bounce_crm_field"]}) if c)
        if crm_bounced and "bounced" not in split_list(person.get("tags")) and not tag_planned(plan, pid, "bounced"):
            plan.book(person, "tags", "bounced", f"the CRM marks the address as bounced ({sync['bounce_crm_field']} "
                      f"{sync['bounce_crm_value']}); the address is kept, the send gate drops it")
        if pid in pending:
            if crm_bounced:
                plan.notes.append(f"Bounce for {pid} confirmed in the CRM (first seen {pending[pid]['since']}).")
            else:
                new_pending[pid] = pending[pid]

    # ---- people: book rows the export did not match
    exported = set(export_ids)
    for p in people:
        pid = p.get("person_id", "")
        if pid in seen_book:
            continue
        cid = p.get("crm_id", "")
        if cid and cid in prev_ids and cid not in exported:
            plan.flag("person", cid, "closed or removed in the CRM",
                      f"book person {pid} was in the last export and is missing now; the outcome is not in "
                      "the export. Nothing was deleted.")
        elif cid:
            plan.flag("person", cid, "CRM id not found in the export", f"book person {pid}")
        elif pid in held:
            plan.flag("person", pid, "not created in the CRM",
                      "this person may already be in the CRM under an ambiguous match; settle that first")
        elif sync.get("create_missing", True):
            plan.crm("create", "person", pid, "*record*", "", f"{p.get('first_name', '')} {p.get('last_name', '')} <{p.get('email', '')}>".strip(),
                     "in the book, not in the CRM")
        if pid in pending:
            new_pending[pid] = pending[pid]

    # ---- accounts (optional export)
    if crm_accounts:
        by_crm = {a.get("crm_id"): a for a in accounts if a.get("crm_id")}
        by_domain = {a.get("domain", "").lower(): a for a in accounts if a.get("domain")}
        amap = sync["account_field_map"]
        for row in crm_accounts:
            cid = row.get(cols["id"], "")
            acct = by_crm.get(cid) or by_domain.get(row.get(amap.get("domain", "domain"), "").lower())
            if acct is None:
                plan.flag("account", cid, "account in the CRM, not in the book", row.get(amap.get("name", "name"), ""))
                continue
            key = "acct:" + (cid or acct.get("account_id", ""))
            for f in sync["account_fields"]:
                b, c = acct.get(f, ""), row.get(amap.get(f, f), "")
                prior = baseline.get(key, {}).get(f)
                if same(b, c, f):
                    new_baseline.setdefault(key, {})[f] = b
                elif not c:
                    plan.crm("update", "account", cid or acct.get("account_id", ""), amap.get(f, f), c, b,
                             "CRM field is blank; a blank never clears the book")
                elif not b or (prior is not None and same(b, prior, f)):
                    plan.notes.append(f"Account {acct.get('account_id')}: CRM {f} is {c!r} (book {b!r}). "
                                      "Put it in input/accounts.csv to take it.")
                elif prior is not None and same(c, prior, f):
                    plan.crm("update", "account", cid or acct.get("account_id", ""), amap.get(f, f), c, b,
                             "changed in the book since the last sync")
                else:
                    plan.conflicts.append({"object": "account", "record_id": cid, "person_id": acct.get("account_id", ""),
                                           "field": f, "book_value": b, "crm_value": c, "baseline": prior or "",
                                           "book_time": "", "crm_time": "",
                                           "reason": "both sides differ and no time says which is newer"})

    # ---- activity: local log
    vocab_ch, vocab_out = set(sync["channels"]), set(sync["outcomes"])
    crm_ext = {r.get(cols["activity_external_id"], "") for r in crm_activity} - {""}
    crm_ext |= {"crm-" + r.get("activity_id", "") for r in crm_activity if r.get("activity_id")}
    person_by_id = {p.get("person_id", ""): p for p in people}
    valid_log, newest = [], watermark
    outcome_changes, new_pending_book = {}, {}
    processed_now = set()
    floor_ts = datetime(1970, 1, 1, tzinfo=timezone.utc)
    ordered = sorted(log_rows, key=lambda x: (parse_ts(x.get("timestamp"), today)[0] or floor_ts, x.get("activity_id", "")))
    for r in ordered:
        aid = r.get("activity_id", "")
        ts, prob = parse_ts(r.get("timestamp"), today)
        if prob or ts is None:
            plan.flag("activity", aid, "bad time in log/activity.csv", prob or "no time")
            continue
        bad = [f"{k} {r.get(k)!r}" for k, vocab in (("channel", vocab_ch), ("outcome", vocab_out))
               if r.get(k) not in vocab]
        if bad:
            plan.flag("activity", aid, "value not on the list", "; ".join(bad) + ". New values are never created.")
            continue
        person = person_by_id.get(r.get("person_id", ""))
        if person is not None and r.get("account_id") and person.get("account_id") \
                and r.get("account_id") != person.get("account_id"):
            plan.flag("activity", aid, "person and account disagree",
                      f"the row says account {r.get('account_id')}; the book has {r.get('person_id')} at "
                      f"{person.get('account_id')}. Fix the row in log/activity.csv and rerun. The activity is "
                      "not planned for the CRM, but a stop outcome on it still applies to the person.")
            if aid not in processed:
                processed_now.add(aid)
                entry = outcome_entry(r.get("outcome"), ts, aid, sync, rules,
                                      " (the log row names another account; applied to the person)")
                if entry:
                    outcome_changes[person["person_id"]] = entry
                if r.get("outcome") == "bounced":
                    pending_bounce(plan, person, ts, new_pending, sync, fmap, "bounce logged", aid)
            continue
        valid_log.append((ts, r))
        if aid not in crm_ext:
            plan.crm("log", "activity", aid, "*activity*", "",
                     f"{r.get('channel')} {r.get('direction')} {r.get('outcome')} {ts.date().isoformat()} person {r.get('person_id')}",
                     "in the log, not yet in the CRM")
        newest = ts if newest is None or ts > newest else newest
        if aid in processed:
            continue  # this row's outcome was already turned into book changes
        if legacy_watermark and watermark is not None and ts <= watermark:
            processed_now.add(aid)  # an older state handled it by time; from now on it is tracked by id
            continue
        if person is None:
            plan.flag("activity", aid, "person not in the book", r.get("person_id", ""))
            continue
        processed_now.add(aid)
        entry = outcome_entry(r.get("outcome"), ts, aid, sync, rules, "")
        if entry:
            outcome_changes[person["person_id"]] = entry  # a later outcome replaces an earlier one
        if r.get("outcome") == "bounced":
            pending_bounce(plan, person, ts, new_pending, sync, fmap, "bounce logged", aid)

    # ---- activity: CRM export rows. Each is brought into the log (to-log.csv) and its outcome
    # becomes book changes in this same run. Rows are tracked by id, never by time, so a row is
    # neither skipped nor counted twice when it is later appended to the log.
    log_ids = {r.get("activity_id", "") for r in log_rows}
    for r in crm_activity:
        ext = r.get(cols["activity_external_id"], "")
        if ext and ext in log_ids:
            continue  # our own log row, echoed back by the CRM
        key = "crm-" + (r.get("activity_id") or ext or "")
        ts, prob = parse_ts(r.get("timestamp", ""), today)
        rid = r.get("activity_id") or ext or r.get(cols["person_id"], "")
        if prob or ts is None:
            plan.flag("activity", rid, "bad time in the CRM activity export", prob or "no time")
            continue
        bad = [f"{k} {r.get(k)!r}" for k, vocab in (("channel", vocab_ch), ("outcome", vocab_out))
               if r.get(k) not in vocab]
        if bad:
            plan.flag("activity", rid, "value not on the list", "; ".join(bad) + ". New values are never created.")
            continue
        person = person_by_crm.get(r.get(cols["person_id"], ""))
        if person is None:
            plan.flag("activity", rid, "CRM activity for someone not in the book", r.get(cols["person_id"], ""))
            continue
        accts = matcher.account_for(r.get(cols["account_domain"], ""), r.get(cols["account_name"], ""))
        if (r.get(cols["account_domain"]) or r.get(cols["account_name"])) and person.get("account_id") not in accts:
            plan.flag("activity", rid, "person and account disagree",
                      f"the CRM row names another account than the book has for {person.get('person_id')}. "
                      "Not brought into the log, but a stop outcome on it still applies to the person.")
            if key not in processed and key not in processed_now:
                processed_now.add(key)
                entry = outcome_entry(r.get("outcome"), ts, f"CRM activity {rid}", sync, rules,
                                      " in the CRM (the row names another account; applied to the person)")
                if entry:
                    entry["from_crm"] = True
                    prev = outcome_changes.get(person["person_id"])
                    if prev is None or prev["since"] <= entry["since"]:
                        outcome_changes[person["person_id"]] = entry
                if r.get("outcome") == "bounced":
                    pending_bounce(plan, person, ts, new_pending, sync, fmap, "bounce in the CRM activity", rid)
            continue
        if key not in log_ids:
            plan.to_log.append({"activity_id": key, "timestamp": ts.isoformat(),
                                "person_id": person["person_id"], "account_id": person.get("account_id", ""),
                                "channel": r.get("channel"), "direction": r.get("direction", ""),
                                "sequence": r.get("sequence", ""), "step": r.get("step", ""), "play_id": "",
                                "angle": "", "opener": "", "outcome": r.get("outcome"), "notes": r.get("notes", ""),
                                "source": "import"})
        if key in processed or key in processed_now:
            continue
        processed_now.add(key)
        entry = outcome_entry(r.get("outcome"), ts, f"CRM activity {rid}", sync, rules, " in the CRM")
        if entry:
            entry["from_crm"] = True
            prev = outcome_changes.get(person["person_id"])
            if prev is None or prev["since"] <= entry["since"]:
                outcome_changes[person["person_id"]] = entry
        if r.get("outcome") == "bounced":
            pending_bounce(plan, person, ts, new_pending, sync, fmap, "bounce in the CRM activity", rid)

    # ---- outcome changes: new ones plus unapplied ones from earlier runs
    export_by_id = {r.get(cols["id"], ""): r for r in crm_people if r.get(cols["id"])}
    for pid, old_entry in sorted(state.get("pending_book", {}).items()):
        if pid not in outcome_changes:
            entry = dict(old_entry)
            entry["runs"] = int(entry.get("runs", 0)) + 1
            outcome_changes[pid] = entry
    for pid, entry in sorted(outcome_changes.items()):
        person = person_by_id.get(pid)
        if person is None:
            continue
        have_tags = set(split_list(person.get("tags")))
        status_done = not entry["status"] or person.get("status") == entry["status"]
        tags_done = set(entry["tags"]) <= have_tags
        crm_status = map_status(export_by_id.get(person.get("crm_id", ""), {}).get(fmap.get("status", "status"), ""), sync)
        crm_done = not entry["status"] or crm_status == entry["status"] or not person.get("crm_id")
        if status_done and tags_done and crm_done:
            if entry.get("runs"):
                plan.notes.append(f"{pid}: the book now shows {entry['reason']}.")
            continue
        if entry.get("runs", 0) > sync["carry_forward_runs"]:
            plan.flag("person", pid, "outcome change never applied",
                      f"{entry['reason']} has been planned {entry['runs']} times and the book still differs. "
                      "Apply it or decide it no longer holds.")
            continue
        carried = f" (carried forward since {entry['since']})" if entry.get("runs") else ""
        if not status_done:
            plan.book(person, "status", entry["status"], entry["reason"] + carried)
        if not crm_done or (not status_done and not person.get("crm_id")):
            plan.crm("update", "person", person.get("crm_id") or pid, fmap.get("status", "status"),
                     "", status_for_crm(entry["status"], sync), entry["reason"] + carried, entry.get("evidence", ""))
        for t in entry["tags"]:
            if t not in have_tags:
                plan.book(person, "tags", t, entry["reason"] + carried)
        new_pending_book[pid] = entry

    # ---- bounces: CRM export (an unchanged file adds nothing new)
    for r in ([] if "bounces" in unchanged else crm_bounces):
        ts, prob = parse_ts(r.get("timestamp", ""), today)
        if prob:
            plan.flag("bounce", r.get("email", ""), "bad time in bounces.csv", prob)
            continue
        person = None
        cid = r.get(cols["id"], "")
        if cid and cid in matcher.by_crm and len(matcher.by_crm[cid]) == 1:
            person = matcher.by_crm[cid][0]
        elif r.get("email", "").lower() in matcher.by_email and len(matcher.by_email[r["email"].lower()]) == 1:
            person = matcher.by_email[r["email"].lower()][0]
        if person is None:
            plan.flag("bounce", r.get("email", "") or cid, "bounce for someone not in the book")
            continue
        if watermark is not None and ts is not None and ts <= watermark:
            continue  # already handled; unconfirmed ones carry forward below
        if ts is not None:
            newest = ts if newest is None or ts > newest else newest
        pending_bounce(plan, person, ts, new_pending, sync, fmap, "bounce in the CRM export", r.get("email", ""))

    # Unconfirmed bounces from earlier runs carry forward, in the book and in the CRM.
    for pid, info in sorted(new_pending.items()):
        person = person_by_id.get(pid)
        if person is not None and "bounced" not in split_list(person.get("tags")) and \
                not any(r["person_id"] == pid and r["field"] == "tags" and "bounced" in r["new_value"] for r in plan.reasons):
            plan.book(person, "tags", "bounced", f"bounce first seen {info['since']}; the address is kept")
        if not any(row["record_id"] in (info.get("crm_id"), pid) and row["field"] == sync["bounce_crm_field"]
                   for row in plan.to_crm):
            plan.crm("update", "person", info.get("crm_id") or pid, sync["bounce_crm_field"], "",
                     sync["bounce_crm_value"], f"bounce not yet confirmed in the CRM (first seen {info['since']})")

    cadence = build_cadence(valid_log, people, sync, holidays)

    # ---- every update names the value the CRM shows now, so a person can check it first
    for r in plan.to_crm:
        if r["action"] == "update" and r["object"] == "person" and not r["current_value"]:
            r["current_value"] = export_by_id.get(r["record_id"], {}).get(r["field"], "")

    # ---- a person without a CRM id gets one create row that carries their other changes
    creates = {r["record_id"]: r for r in plan.to_crm if r["action"] == "create"}
    kept = []
    for r in plan.to_crm:
        if r["action"] == "update" and r["record_id"] in creates:
            c = creates[r["record_id"]]
            c["new_value"] += f"; {r['field']}={r['new_value']}"
            c["reason"] += f"; {r['reason']}"
            continue
        kept.append(r)
    plan.to_crm = kept

    # ---- create and log rows are not safe to apply twice. One planned on an earlier run and still
    # not in the export may already be in the CRM: say so, so the person searches before re-applying.
    earlier = state.get("planned_writes", {})
    planned_writes = {}
    for r in plan.to_crm:
        if r["action"] not in ("create", "log"):
            continue
        key = f"{r['action']}:{r['record_id']}"
        first = earlier.get(key, today.isoformat())
        planned_writes[key] = first
        if first < today.isoformat():
            r["reason"] += (f" (planned first on {first} and still not in the export: search the CRM for it "
                            "before applying it again; a second copy is a duplicate)")
            r["repeat"] = "yes"

    # ---- number the CRM plan; the first rows are the pilot batch
    order = {"update": 0, "create": 1, "log": 2}
    plan.to_crm.sort(key=lambda r: (order.get(r["action"], 9), r["object"], r["record_id"], r["field"]))
    for i, r in enumerate(plan.to_crm, 1):
        r["row_id"] = f"S{i:03d}"
        r["pilot"] = "yes" if i <= sync["pilot_rows"] else ""
    for i, r in enumerate(plan.review, 1):
        r["review_id"] = f"R{i:03d}"

    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "to-crm.csv", plan.to_crm, TO_CRM_COLS)
    book_cols = ["person_id", "account_id", "crm_id"] + [f for f in sync["fields"] if f not in ("crm_id",)] + ["tags"]
    write_csv(out / "to-book.csv", sorted(plan.to_book.values(), key=lambda r: (r.get("person_id") == "", r.get("person_id"), r.get("crm_id"))), book_cols)
    write_csv(out / "to-book-reasons.csv", plan.reasons, REASON_COLS)
    plan.account_updates, plan.live_kept = account_updates(accounts, crm_accounts, opportunities, cols)
    write_csv(out / "to-book-accounts.csv", plan.account_updates, ACCT_UPDATE_COLS)
    write_csv(out / "to-log.csv", sorted(plan.to_log, key=lambda r: (r["timestamp"], r["activity_id"])), LOG_COLS)
    write_csv(out / "conflicts.csv", plan.conflicts, CONFLICT_COLS)
    write_csv(out / "review.csv", plan.review, REVIEW_COLS)
    write_csv(out / "cadence.csv", cadence, CADENCE_COLS)

    copy_result = None
    if rung == "copy":
        copy_result = apply_to_copy(out, crm_people, exp_cols, plan.to_crm, cols)

    new_state = {
        "last_run": today.isoformat(),
        "watermark": newest.isoformat() if newest else "",
        "datasets": ds_state,
        "export_ids": sorted(set(export_ids)),
        "baseline": {k: new_baseline[k] for k in sorted(new_baseline)},
        "pending_bounces": {k: new_pending[k] for k in sorted(new_pending)},
        "pending_book": {k: new_pending_book[k] for k in sorted(new_pending_book)},
        "processed_activity": sorted(processed | processed_now),
        "planned_writes": {k: planned_writes[k] for k in sorted(planned_writes)},
        "fingerprint": fp,
        "input_state": state,
    }
    # The copy rung only shows a result, and a rerun on the same inputs must not move the state on.
    state_saved = rung == "plan" and not rerun
    if state_saved:
        write_atomic(state_path, json.dumps(new_state, indent=2, sort_keys=True) + "\n")

    summary = {
        "export_people": len(crm_people), "matched": accounted["matched"], "new_in_crm": accounted["new_in_crm"],
        "review_people": accounted["review"], "to_crm": len(plan.to_crm),
        "to_book_rows": len(plan.to_book), "to_log": len(plan.to_log), "conflicts": len(plan.conflicts),
        "review": len(plan.review), "pending_bounces": len(new_pending), "unchanged": unchanged,
        "state_saved": state_saved, "rerun": rerun,
    }
    assert summary["matched"] + summary["new_in_crm"] + summary["review_people"] == len(crm_people), \
        "every export row must be accounted for"
    write_report(out, plan, summary, sync, rung, copy_result, wm_problem, today, mapping_confirmed)
    return summary


ACCOUNT_STATUSES = ("active", "hold", "live_deal", "archived")
CLOSED_WORDS = ("true", "yes", "1", "closed", "y")


def account_updates(accounts, crm_accounts, opportunities, cols):
    """Account status, owner and relationship from the CRM, for account-book's
    input/account-updates.csv. The CRM is the record for these three fields.
    An open opportunity sets live_deal. A book live_deal goes back to active only
    when the export has that account's opportunities and every one is closed; an
    account missing from the export stays live_deal (a partial export must not
    reopen outbound) and is listed in `kept`. A blank never clears.
    Returns (rows, kept)."""
    by_crm = {a.get("crm_id"): a for a in accounts if a.get("crm_id")}
    rows, kept = {}, []

    def put(acct, field, value, reason):
        if not value or value == acct.get(field, ""):
            return
        row = rows.setdefault(acct["account_id"], {"account_id": acct["account_id"],
                                                   "crm_id": acct.get("crm_id", ""), "reason": ""})
        row[field] = value
        row["reason"] = "; ".join(x for x in (row["reason"], reason) if x)

    for c in crm_accounts:
        acct = by_crm.get(c.get(cols["id"], ""))
        if acct is None:
            continue
        put(acct, "owner", (c.get("owner") or "").strip(), "CRM account owner")
        put(acct, "relationship", (c.get("relationship") or "").strip().lower(), "CRM account relationship")
        status = (c.get("status") or "").strip().lower().replace(" ", "_")
        if status in ACCOUNT_STATUSES:
            put(acct, "status", status, "CRM account status")
    if opportunities:
        open_by_acct, seen = {}, set()
        for o in opportunities:
            seen.add(o.get("account_crm_id", ""))
            if (o.get("is_closed") or "").strip().lower() in CLOSED_WORDS:
                continue
            open_by_acct.setdefault(o.get("account_crm_id", ""), []).append(o)
        for cid, acct in by_crm.items():
            opps = open_by_acct.get(cid)
            if opps:
                names = ", ".join(f"{o.get('opportunity_id', '?')} ({o.get('stage', 'no stage')})" for o in opps)
                put(acct, "status", "live_deal", f"open opportunity {names}: the deal owner leads")
            elif (acct.get("status") or "").strip().lower() == "live_deal":
                if cid in seen:
                    put(acct, "status", "active", "no open opportunity in the export: the deal closed")
                else:
                    kept.append(acct["account_id"])
    return sorted(rows.values(), key=lambda r: r["account_id"]), sorted(kept)


def tag_planned(plan, pid, tag):
    """True when this run already plans `tag` for the person in to-book.csv."""
    return tag in split_list(plan.to_book.get(pid, {}).get("tags"))


def pending_bounce(plan, person, ts, pending, sync, fmap, reason, evidence):
    pid = person["person_id"]
    since = (ts.date().isoformat() if ts else "")
    if pid not in pending:
        pending[pid] = {"since": since, "crm_id": person.get("crm_id", ""), "email": person.get("email", "")}
    if "bounced" not in split_list(person.get("tags")) and not tag_planned(plan, pid, "bounced"):
        plan.book(person, "tags", "bounced", f"{reason}; the address is kept, the send gate drops it")
    plan.crm("update", "person", person.get("crm_id") or pid, sync["bounce_crm_field"], "",
             sync["bounce_crm_value"], reason, evidence)


def build_cadence(valid_log, people, sync, holidays):
    """Sequence state per person: active with the next due date, replied, or stopped with a reason."""
    engaged, stops = set(sync["engaged_outcomes"]), set(sync["stop_outcomes"])
    people_by_id = {p.get("person_id", ""): p for p in people}
    state = {}
    replied_accounts = {}
    for ts, r in sorted(valid_log, key=lambda x: (x[0], x[1].get("activity_id", ""))):
        pid = r.get("person_id", "")
        acct = r.get("account_id") or people_by_id.get(pid, {}).get("account_id", "")
        if r.get("outcome") in engaged and r.get("direction", "in") in ("in", "out"):
            replied_accounts.setdefault(acct, (ts, pid))
        seq = r.get("sequence", "")
        if not seq:
            continue
        cur = state.setdefault((pid, seq), {"person_id": pid, "account_id": acct, "sequence": seq,
                                            "last_step": "", "last_touch": "", "state": "active",
                                            "reason": "", "next_due": ""})
        if r.get("step"):
            cur["last_step"] = r["step"]
        cur["last_touch"] = ts.date().isoformat()
        if cur["state"] != "active":
            continue
        if r.get("outcome") in engaged:
            cur["state"], cur["reason"] = "replied", f"{r.get('outcome')} {ts.date().isoformat()}"
        elif r.get("outcome") in stops:
            cur["state"], cur["reason"] = "stopped", f"{r.get('outcome')} {ts.date().isoformat()}"
    rows = []
    for (pid, seq), cur in sorted(state.items()):
        acct_reply = replied_accounts.get(cur["account_id"])
        if cur["state"] == "active" and acct_reply and acct_reply[1] != pid:
            cur["state"], cur["reason"] = "stopped", f"reply at the account from {acct_reply[1]}"
        if cur["state"] == "active" and cur["last_touch"]:
            last = date.fromisoformat(cur["last_touch"])
            cur["next_due"] = add_business_days(last, sync["next_step_business_days"], holidays).isoformat()
        rows.append(cur)
    return rows


def apply_to_copy(out, crm_people, cols_in, to_crm, cols):
    """Apply planned person updates to a copy of the export. Checks current_value first."""
    copy_rows = [dict(r) for r in crm_people]
    by_id = {r.get(cols["id"], ""): r for r in copy_rows if r.get(cols["id"])}
    log = []
    for r in to_crm:
        if r["object"] != "person" or r["action"] != "update":
            log.append({"row_id": r["row_id"], "status": "skipped", "error": f"{r['action']} {r['object']} is not applied to the copy"})
            continue
        target = by_id.get(r["record_id"])
        if target is None:
            log.append({"row_id": r["row_id"], "status": "failed", "error": "record not in the export"})
            continue
        field = r["field"]
        now = target.get(field, "")
        if now == r["new_value"]:
            log.append({"row_id": r["row_id"], "status": "skipped", "error": "already right"})
        elif r["current_value"] and now != r["current_value"]:
            log.append({"row_id": r["row_id"], "status": "drift", "error": f"expected {r['current_value']!r}, found {now!r}"})
        else:
            target[field] = r["new_value"]
            log.append({"row_id": r["row_id"], "status": "applied", "error": ""})
    fields = list(cols_in)
    for r in to_crm:
        if r["object"] == "person" and r["action"] == "update" and r["field"] not in fields:
            fields.append(r["field"])
    write_csv(out / "copy" / "people.csv", copy_rows, fields)
    write_csv(out / "copy" / "row-log.csv", log, ["row_id", "status", "error"])
    counts = {}
    for row in log:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def write_report(out, plan, s, sync, rung, copy_result, wm_problem, today, mapping_confirmed=False):
    lines = [f"# CRM sync plan {today.isoformat()}", ""]
    if not mapping_confirmed:
        lines += ["**Mapping unconfirmed:** this plan uses the field mapping in gtm.json (table below). Confirm "
                  "it before applying any row; a wrong mapping writes good data into the wrong field.", ""]
    lines += ["## Needs you", ""]
    needs = []
    unknown = [r for r in plan.review if r["issue"] == "unknown CRM status"]
    if unknown:
        needs.append(f"{len(unknown)} CRM status value(s) are not in `sync.status_map` (see `review.csv`). "
                     "Map them in gtm.json or fix them in the CRM; nothing was changed for them.")
    if plan.conflicts:
        needs.append(f"Settle {len(plan.conflicts)} conflict(s) in `conflicts.csv`: both sides changed and nothing says which is newer.")
    if plan.review:
        needs.append(f"Look at {len(plan.review)} item(s) in `review.csv` (ambiguous matches, unknown values, records gone from the CRM).")
    pilot = [r for r in plan.to_crm if r["pilot"] == "yes"]
    if plan.to_crm:
        needs.append(f"Apply the {len(pilot)} pilot row(s) in `to-crm.csv` first, check them in the CRM, then the rest. "
                     "Check each row's current value before you change it.")
    repeats = [r for r in plan.to_crm if r.get("repeat") == "yes"]
    if repeats:
        needs.append(f"{len(repeats)} create or log row(s) in `to-crm.csv` were planned on an earlier run and the export "
                     "still does not show them. Search the CRM for each before applying it again: applying twice "
                     "makes a duplicate. Add the CRM activity export to `input/crm-export/` so applied rows drop off.")
    if plan.to_book:
        needs.append("Copy `to-book.csv` into `input/` (for example `input/crm-sync.csv`), add it to `book.sources` in "
                     "gtm.json, and rebuild the book with account-book.")
    status_rows = [r for r in plan.reasons if r["field"] == "status" and r["new_value"] != "do_not_contact"]
    if status_rows:
        needs.append(f"Set {len(status_rows)} status change(s) in `book/people.csv` yourself (listed in "
                     "`to-book-reasons.csv`). account-book only takes do-not-contact from a source file.")
    acct_updates = getattr(plan, "account_updates", [])
    if acct_updates:
        live = [r["account_id"] for r in acct_updates if r.get("status") == "live_deal"]
        needs.append(f"Copy `to-book-accounts.csv` to `input/account-updates.csv` and rebuild the book: "
                     f"{len(acct_updates)} account change(s) from the CRM."
                     + (f" Open deals at {', '.join(live)}: outbound stops there once the book is rebuilt." if live else ""))
    kept = getattr(plan, "live_kept", [])
    if kept:
        needs.append(f"Live deal kept at {', '.join(kept)}: the opportunities export has no row for "
                     + ("it" if len(kept) == 1 else "them")
                     + ". Outbound stays off until an export shows the deal closed. Check the export is complete.")
    if plan.to_log:
        needs.append(f"Append the {len(plan.to_log)} row(s) in `to-log.csv` to `log/activity.csv`.")
    if wm_problem:
        needs.append(f"The saved watermark was ignored: {wm_problem}.")
    lines += [f"- {n}" for n in needs] or ["- Nothing. The book and the CRM agree."]
    lines += ["", "## Field mapping (book -> CRM column)", "", "| Book | CRM |", "|---|---|"]
    lines += [f"| {f} | {sync['field_map'].get(f, f)} |" for f in sync["fields"]]
    lines += ["", "## Every export row accounted for", "",
              f"- CRM people rows: {s['export_people']} = matched {s['matched']} + new in CRM {s['new_in_crm']} + review {s['review_people']}",
              f"- Planned CRM changes: {s['to_crm']} ({len(pilot)} pilot)",
              f"- Book changes: {s['to_book_rows']} row(s), reasons in `to-book-reasons.csv`",
              f"- Activity rows to add to the log: {s['to_log']}",
              f"- Conflicts: {s['conflicts']}; review items: {s['review']}",
              f"- Bounces waiting for CRM confirmation: {s['pending_bounces']}"]
    if s["unchanged"]:
        lines.append(f"- Unchanged since the last run: {', '.join(s['unchanged'])}")
    if s["rerun"]:
        lines.append("- Same inputs as the last run: this is the same plan, and the sync state was not moved on.")
    elif not s["state_saved"]:
        lines.append("- Copy rung: the sync state was not saved. Run the plan rung to record this sync.")
    if plan.notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in plan.notes]
    if copy_result is not None:
        lines += ["", "## Copy rung", "", "Planned person updates were applied to `copy/people.csv`, a copy of the "
                  "export. The row log is `copy/row-log.csv`.", ""]
        lines += [f"- {k}: {v}" for k, v in sorted(copy_result.items())]
    lines += ["", "Nothing was sent and no CRM was changed. A live write is a person's action, one rung at a time: "
              "plan, then copy, then live. A bare yes never skips a rung."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan a two-way sync between the GTM book and a CRM export. Files only.")
    ap.add_argument("--workspace", default="gtm")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    ap.add_argument("--rung", default="plan", help="plan (default) or copy")
    ap.add_argument("--out", help="output folder (default <workspace>/sync)")
    ap.add_argument("--mapping-confirmed", action="store_true",
                    help="the user confirmed the field mapping (otherwise the report says it is unconfirmed)")
    args = ap.parse_args(argv)
    try:
        today = date.fromisoformat(args.today)
    except ValueError:
        ap.error("--today must be YYYY-MM-DD")
    try:
        s = run(args.workspace, today, args.rung, args.out, mapping_confirmed=args.mapping_confirmed)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if s.get("stopped"):
        for t in s["floor_trips"]:
            print(f"STOPPED: {t}")
        if s.get("stale"):
            print("Renamed the last run's plan files: " + ", ".join(s["stale"]))
        print("Nothing was planned. Export again and rerun.")
        return 1
    print(f"CRM people rows {s['export_people']}: matched {s['matched']}, new in CRM {s['new_in_crm']}, review {s['review_people']}")
    print(f"Planned CRM changes {s['to_crm']}; book rows {s['to_book_rows']}; log rows {s['to_log']}; "
          f"conflicts {s['conflicts']}; review {s['review']}; bounces waiting {s['pending_bounces']}")
    print("Nothing was sent and no CRM was changed. Read sync/report.md first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
