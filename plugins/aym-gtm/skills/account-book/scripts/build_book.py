#!/usr/bin/env python3
"""Build the prospect book (one row per person) and the account book (one row
per account) from raw source files, keeping the user's edits on every rebuild.

Writes only under the book folder:
  people.csv, accounts.csv, fixes.csv, conflicts.csv, accounts.md,
  .built/people.csv and .built/accounts.csv (the merged source values from the
  last build, used to tell a user edit from a source change), and, with --export,
  export.csv and export-left-out.csv.

Standard library only. No network. Never writes to a CRM or a sequencer.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtm_fit import fit as icp_fit  # noqa: E402  (shared ICP-fit rule, copied in four skills)

PEOPLE_COLS = ["person_id", "account_id", "first_name", "last_name", "title", "email",
               "email_status", "email_score", "phone", "linkedin_url", "country", "timezone",
               "status", "last_touch_date", "sequence", "tags", "notes", "crm_id", "source"]
PEOPLE_ADDED = ["persona", "lane", "role", "send_ok", "send_block_reason", "followup_ok",
                "followup_block_reason", "call_ok", "call_block_reason", "linkedin_ok",
                "linkedin_block_reason", "timezone_source", "next_step", "new_note"]
ACCOUNT_COLS = ["account_id", "name", "domain", "other_domains", "employees", "industry",
                "country", "tier", "relationship", "status", "owner", "crm_id", "notes"]
ACCOUNT_ADDED = ["people_count", "buying_group_count", "send_ok_count", "readiness",
                 "lanes_covered", "lanes_missing", "strategy", "strategy_reason",
                 "strategy_override", "pain", "pain_status", "next_step", "tags"]
COMPUTED_PEOPLE = {"persona", "lane", "role", "send_ok", "send_block_reason", "call_ok",
                   "call_block_reason", "linkedin_ok", "linkedin_block_reason", "timezone_source"}
COMPUTED_ACCOUNTS = {"people_count", "buying_group_count", "send_ok_count", "readiness",
                     "lanes_covered", "lanes_missing", "strategy", "strategy_reason"}

DEFAULT_GATE = {
    "email_status_ok": ["verified"],
    "min_email_score": 80,
    "block_catch_all": True,
    "require_own_domain": True,
    "countries": ["US", "CA"],
}
# Shared top-level rules in gtm.json. Each value here is only the default.
DEFAULT_RULES = {
    "stop_statuses": ["hold", "booked", "not_interested", "wrong_person", "left",
                      "do_not_contact", "archived"],
    "dnc_tags": ["opted_out", "dnc_all"],
    "left_tags": ["moved"],
    "channel_block_tags": {"email": ["bounced"], "call": ["dnc_phone", "phone_failed"], "linkedin": []},
    "not_buyer_titles": [r"\bintern\b", "student", "recruit", "sales rep", "account executive"],
    "exclude_relationships": ["competitor", "customer", "partner", "parent_decides"],
    "dnc_note_patterns": ["do not contact", "don't contact", "not to contact",
                          "unsubscribe", "remove me", "stop emailing"],
}
# Strategies where outbound stays off: excluded accounts, accounts on hold, and live
# deals (the deal owner leads those).
NO_OUTBOUND = {"excluded", "hold", "live"}
DEFAULT_BOOK = {
    "sources": ["input/researched.csv", "input/verified.csv", "input/people.csv"],
    "ready_min": 2,
    # Ready also needs these roles among the send-ready buyers (Oct 22 review).
    "ready_requires_roles": ["decision_maker"],
    "priority_tiers": ["P1", "P2"],
    "area_code_tz": {},
    "fix_fields": ["first_name", "last_name", "title", "email", "phone", "linkedin_url", "country", "status"],
    "required_sources": ["input/people.csv"],
    "reengage_account_tags": ["lost_deal"],
    "reengage_person_tags": ["past_reply"],
    "reply_tags": ["replied", "past_reply", "not_now"],
}


def load_config(workspace):
    path = workspace / "gtm.json"
    cfg = json.loads(path.read_text()) if path.exists() else {}
    gate = dict(DEFAULT_GATE)
    gate.update(cfg.get("send_gate", {}))
    book = dict(DEFAULT_BOOK)
    book.update(cfg.get("book", {}))
    personas = []
    for p in cfg.get("personas", []):
        pats = [re.compile(x, re.I) for x in p.get("title_patterns", [])]
        personas.append((p["id"], p.get("lane", ""), p.get("role", ""), pats))
    lanes = []
    for _, lane, _, _ in personas:
        if lane and lane not in lanes:
            lanes.append(lane)
    rules = {
        "icp": cfg.get("icp", {}),
        "stop_statuses": cfg.get("stop_statuses", DEFAULT_RULES["stop_statuses"]),
        "dnc_tags": cfg.get("dnc_tags", DEFAULT_RULES["dnc_tags"]),
        "left_tags": cfg.get("left_tags", DEFAULT_RULES["left_tags"]),
        "channel_block_tags": dict(DEFAULT_RULES["channel_block_tags"], **cfg.get("channel_block_tags", {})),
        "not_buyer": [re.compile(x, re.I) for x in cfg.get("not_buyer_titles", DEFAULT_RULES["not_buyer_titles"])],
        "exclude_relationships": cfg.get("icp", {}).get("exclude_relationships",
                                                        DEFAULT_RULES["exclude_relationships"]),
        "dnc_notes": [x.lower() for x in cfg.get("clean", {}).get("dnc_note_patterns",
                                                                  DEFAULT_RULES["dnc_note_patterns"])],
    }
    return cfg, gate, book, personas, lanes, rules


def to_num(value):
    """Read a number written as 1200, "1,200" or " 1200 ". Blank or unreadable gives None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def read_csv(path):
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
        return rows, list(reader.fieldnames or [])


def write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def split_list(value):
    return [x.strip() for x in (value or "").split(";") if x.strip()]


def join_list(items):
    seen = []
    for x in items:
        if x and x not in seen:
            seen.append(x)
    return ";".join(seen)


def norm_name(first, last):
    text = f"{first} {last}".lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text)).strip()


GENERATED_ID = re.compile(r"^p-[0-9a-f]{8}x*$")


def is_generated_id(pid):
    """True for an id this script made up (p- plus 8 hex), not one from a source."""
    return bool(GENERATED_ID.match(pid or ""))


def make_id(row):
    key = (row.get("email") or "").lower() or "|".join(
        [norm_name(row.get("first_name"), row.get("last_name")), row.get("account_id", "")])
    return "p-" + hashlib.sha1(key.encode()).hexdigest()[:8]


class Index:
    """Match ladder: person id, CRM id, email, then exact normalized name at the
    same account. Never fuzzy. The name rung skips anyone whose id or email
    clearly differs, and a name that still points at two people is ambiguous."""

    def __init__(self):
        self.by = {"person_id": {}, "crm_id": {}, "email": {}}
        self.by_name = {}
        self.rows = {}

    def add(self, key, row):
        self.rows[key] = row
        for field in ("person_id", "crm_id"):
            if row.get(field):
                self.by[field].setdefault(row[field], key)
        if row.get("email"):
            self.by["email"].setdefault(row["email"].lower(), key)
        name = norm_name(row.get("first_name"), row.get("last_name"))
        if name and row.get("account_id"):
            self.by_name.setdefault((name, row["account_id"]), set()).add(key)

    @staticmethod
    def _clashes(a, b):
        for field in ("person_id", "crm_id", "email"):
            x, y = (a.get(field) or "").lower(), (b.get(field) or "").lower()
            if x and y and x != y:
                return True
        return False

    def find(self, row):
        for field in ("person_id", "crm_id"):
            if row.get(field) and row[field] in self.by[field]:
                return self.by[field][row[field]], None
        if row.get("email") and row["email"].lower() in self.by["email"]:
            return self.by["email"][row["email"].lower()], None
        name = norm_name(row.get("first_name"), row.get("last_name"))
        keys = self.by_name.get((name, row.get("account_id", "")), set()) if name else set()
        keys = sorted(k for k in keys if not self._clashes(row, self.rows[k]))
        if len(keys) == 1:
            return keys[0], None
        if len(keys) > 1:
            return None, "same name matches more than one person at this account"
        return None, None


def merge_sources(sources, conflicts):
    """Sources come in precedence order. A higher source's non-empty value wins;
    a lower source only fills blanks. Tags are joined. A real person id or CRM id
    from any source is kept; an id is generated only when no source has one."""
    merged = {}
    order = []
    index = Index()
    for name, rows in sources:
        for raw in rows:
            row = dict(raw)
            key, problem = index.find(row)
            if problem:
                conflicts.append({"person_id": row.get("person_id", ""), "field": "match",
                                  "book_value": "", "source_value": norm_name(row.get("first_name"), row.get("last_name")),
                                  "source": name, "note": problem + "; kept as a separate row"})
            if key is None:
                key = f"k{len(order)}"
                row["source"] = name
                merged[key] = row
                order.append(key)
                index.add(key, row)
                continue
            target = merged[key]
            for field, value in row.items():
                if field == "source":
                    continue
                if field == "tags":
                    target["tags"] = join_list(split_list(target.get("tags")) + split_list(value))
                elif value and not target.get(field):
                    target[field] = value
            target["source"] = join_list(split_list(target.get("source")) + [name])
            index.add(key, target)
    out, taken = [], set()
    for key in order:
        row = merged[key]
        generated = not row.get("person_id")
        pid = row.get("person_id") or make_id(row)
        while pid in taken:
            pid = pid + "x"
        taken.add(pid)
        row["person_id"] = pid
        row["_generated_id"] = generated
        out.append(row)
    return out


def notes_say_dnc(row, rules):
    text = (row.get("notes") or "").lower()
    return any(p in text for p in rules["dnc_notes"])


def dnc_from_sources(row, rules):
    """A source that says the person asked not to be contacted: the status, an
    opt-out tag from `dnc_tags`, or a do-not-contact phrase in the notes. Left
    tags (`left_tags`, such as moved) block contact but never mean do-not-contact."""
    tags = set(split_list(row.get("tags")))
    return (row.get("status") == "do_not_contact"
            or bool(tags & set(rules["dnc_tags"]))
            or notes_say_dnc(row, rules))


def reconcile(merged, book_rows, built_rows, today, conflicts, rules, area_map):
    """Apply the edits-win rules against the existing book.

    `.built/` holds the merged source values from the last build. A field counts
    as a user edit when the book differs from that source value, so an edit
    survives any number of rebuilds. For a row the user added by hand, every
    value counts as an edit. Returns (book rows, source rows to save in .built)."""
    built = {r["person_id"]: r for r in built_rows if r.get("person_id")}
    book_index = Index()
    book_by_key = {}
    for r in book_rows:
        book_by_key[r["person_id"]] = r
        # A made-up id must not block a match with the same person's real id.
        book_index.add(r["person_id"], dict(r, person_id="") if is_generated_id(r["person_id"]) else r)
    out, used, sources_out = [], set(), []
    adopted = []
    for new in merged:
        probe = {k: v for k, v in new.items() if not (k == "person_id" and new.get("_generated_id"))}
        key, _ = book_index.find(probe)
        if key is None and new.get("_generated_id") and new["person_id"] in book_by_key:
            key = new["person_id"]
        if key is None or key in used:
            row = dict(new)
            row["status"] = row.get("status") or "active"
            if dnc_from_sources(new, rules):
                row["status"] = "do_not_contact"
            row["_edited"] = set()
            out.append(row)
            sources_out.append(dict(new))
            continue
        used.add(key)
        old = book_by_key[key]
        last = built.get(key)
        row = dict(new)
        new_id = key
        if is_generated_id(key) and not new.get("_generated_id") and new.get("person_id") and new["person_id"] != key:
            # The book held this person under a made-up id; a source now has the real one.
            new_id = new["person_id"]
            adopted.append((key, new_id))
            conflicts.append({"person_id": new_id, "field": "person_id", "book_value": key,
                              "source_value": new_id, "source": new.get("source", ""),
                              "note": "made-up id replaced by the id from a source; your edits were kept"})
        row["person_id"] = new_id
        row["_edited"] = set()
        saved = dict(new, person_id=new_id)
        if last is not None:
            # A source that goes blank keeps its last value in .built, so the
            # book's (old source) value is not mistaken for a user edit later.
            for f, v in last.items():
                if v and not saved.get(f):
                    saved[f] = v
        sources_out.append(saved)
        for field in sorted(set(old) | set(new)):
            if field in COMPUTED_PEOPLE or field == "person_id" or field == "source" or field.startswith("_"):
                continue
            if field == "crm_id" and not old.get(field) and new.get(field):
                row[field] = new[field]
                continue
            book_val, new_val = old.get(field, ""), new.get(field, "")
            built_val = last.get(field, "") if last is not None else ""
            if field == "tags":
                row["tags"] = join_list(split_list(book_val) + split_list(new_val))
            elif field == "notes":
                row["notes"] = book_val or new_val
            elif field in ("status", "next_step", "new_note"):
                row[field] = book_val or (new_val if field == "status" else "")
                if (field == "status" and last is not None and new_val and book_val
                        and new_val != book_val and new_val != built_val):
                    conflicts.append({"person_id": key, "field": "status", "book_value": book_val,
                                      "source_value": new_val, "source": new.get("source", ""),
                                      "note": "a source changed status; the book keeps yours"})
            elif field == "timezone" and not _timezone_edited(old, book_val, built_val, area_map):
                row[field] = new_val
            elif (last is None and book_val) or (last is not None and book_val != built_val):
                row[field] = book_val  # the user edited this field
                if book_val != new_val:
                    row["_edited"].add(field)
            elif not new_val:
                row[field] = book_val  # never delete because a source went blank
            else:
                row[field] = new_val
        row["status"] = row.get("status") or "active"
        row["source"] = join_list(split_list(old.get("source")) + split_list(new.get("source")))
        if dnc_from_sources(new, rules):
            row["status"] = "do_not_contact"
        out.append(row)
    for r in book_rows:
        if r["person_id"] not in used:
            row = dict(r)
            row["_edited"] = set()
            if r["person_id"] in built:
                sources_out.append(built[r["person_id"]])  # a source dropped them; keep the last values
            else:
                row["source"] = row.get("source") or "manual"
            out.append(row)
    for row in out:
        note = row.get("new_note", "").strip()
        if note:
            lines = [ln for ln in row.get("notes", "").split(" | ") if ln]
            lines.append(f"{today}: {note}")
            row["notes"] = " | ".join(lines)
            row["new_note"] = ""
    return out, sources_out, adopted


def _timezone_edited(old, book_val, built_val, area_map):
    """The script fills a missing time zone from the area code. That value is not
    a user edit. A zone marked manual, or one that differs from both the source
    and the area-code guess, is."""
    if not book_val:
        return False
    if old.get("timezone_source") == "manual":
        return True
    if book_val == built_val:
        return False
    if old.get("timezone_source") == "area_code_approx" and book_val == derive_tz(old.get("phone"), area_map):
        return False
    return True


def classify(title, personas):
    for pid, lane, role, pats in personas:
        if any(p.search(title or "") for p in pats):
            return pid, lane, role
    return "", "", ""


def account_domains(acct):
    return [d.lower() for d in [acct.get("domain", "")] + split_list(acct.get("other_domains")) if d]


def _common_blocks(person, acct, rules, channel):
    """Checks that apply to every channel: who the person is, what they asked
    for, and whether outbound is allowed at their account at all."""
    reasons = []
    status = person.get("status", "")
    if status in rules["stop_statuses"]:
        reasons.append(f"status {status}")
    tags = set(split_list(person.get("tags")))
    hit = sorted(tags & (set(rules["dnc_tags"]) | set(rules["channel_block_tags"].get(channel, []))))
    if hit:
        reasons.append("tag " + ",".join(hit))
    left = sorted(tags & set(rules["left_tags"]))
    if left:
        reasons.append("tag " + ",".join(left) + ": person may have left (set status left if true)")
    if notes_say_dnc(person, rules):
        reasons.append("notes say do not contact")
    if any(p.search(person.get("title") or "") for p in rules["not_buyer"]):
        reasons.append("title is not a buyer")
    rel = acct.get("relationship", "")
    if rel and rel in rules["exclude_relationships"]:
        reasons.append(f"account relationship is {rel}")
    strategy = acct.get("strategy", "")
    if strategy in NO_OUTBOUND:
        held = "account is on hold" if acct_status(acct) == "hold" else \
            f"account held: {acct.get('strategy_reason') or 'hold'}"
        why = {"live": "a live deal is open; the deal owner leads",
               "hold": held, "excluded": "account is excluded"}[strategy]
        if not (strategy == "excluded" and rel and rel in rules["exclude_relationships"]):
            reasons.append(why)
    else:
        verdict, reason = icp_fit(acct, rules["icp"])
        if verdict == "unknown":
            reasons.append(f"fit unknown: {reason}")
    return reasons


def send_gate(person, acct, gate, rules):
    """Email checks shared by send_ok and followup_ok. Returns the block reasons."""
    reasons = _common_blocks(person, acct, rules, "email")
    email = person.get("email", "")
    est = person.get("email_status", "")
    if not email:
        reasons.append("no email")
    else:
        if gate["block_catch_all"] and est == "catch_all":
            reasons.append("catch-all domain")
        elif est not in gate["email_status_ok"]:
            reasons.append(f"email {est or 'unchecked'}")
        floor = gate.get("min_email_score")
        if floor is not None:
            score = person.get("email_score", "")
            value = to_num(score)
            if not score:
                reasons.append("no email score")
            elif value is None:
                reasons.append("email score unreadable")
            elif value < float(floor):
                reasons.append(f"email score below {floor}")
        if gate["require_own_domain"]:
            dom = email.split("@")[-1].lower()
            owned = account_domains(acct)
            if not any(dom == d or dom.endswith("." + d) for d in owned):
                reasons.append("email not on the account's domains")
    countries = gate.get("countries") or []
    country = person.get("country") or acct.get("country", "")
    if countries and country not in countries:
        reasons.append(f"country {country or 'unknown'}")
    return reasons


def first_touch_gate(person, acct, gate, rules):
    """send_ok: may get a new first touch. Anyone already in a sequence is out."""
    reasons = send_gate(person, acct, gate, rules)
    if person.get("sequence"):
        reasons = reasons + [f"already in sequence {person['sequence']}"]
    return ("no", "; ".join(reasons)) if reasons else ("yes", "")


def followup_gate(person, acct, gate, rules, group=(), reply_tags=()):
    """followup_ok: may get the next step of the sequence they are already in.
    Same checks as send_ok except the sequence rule; no sequence means no follow-up.
    Any reply stops the sequence: the person's own, or anyone's at the same account."""
    reasons = send_gate(person, acct, gate, rules)
    if not person.get("sequence"):
        reasons = reasons + ["not in a sequence"]
    replies = set(reply_tags)
    if set(split_list(person.get("tags"))) & replies:
        reasons = reasons + ["replied: a person handles this, not the sequence"]
    elif any(set(split_list(o.get("tags"))) & replies for o in group if o is not person):
        reasons = reasons + ["someone at this account replied: the account's sequences stop"]
    return ("no", "; ".join(reasons)) if reasons else ("yes", "")


def call_gate(person, acct, rules):
    reasons = _common_blocks(person, acct, rules, "call")
    if not person.get("phone"):
        reasons.append("no phone")
    return ("no", "; ".join(reasons)) if reasons else ("yes", "")


def linkedin_gate(person, acct, rules):
    """linkedin_ok: may get a LinkedIn touch (connect note or message). The same
    person and account blocks as email and calls, plus a profile link."""
    reasons = _common_blocks(person, acct, rules, "linkedin")
    if not (person.get("linkedin_url") or "").strip():
        reasons.append("no LinkedIn URL")
    return ("no", "; ".join(reasons)) if reasons else ("yes", "")


def derive_tz(phone, area_map):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    return area_map.get(digits[:3]) if len(digits) == 10 else None


def time_zone(person, area_map):
    """Data first, then the phone's area code (marked approximate). A value the
    user typed in the book wins and is labelled manual."""
    tz = person.get("timezone", "")
    if tz:
        if "timezone" in person.get("_edited", ()):
            return tz, "manual"
        return tz, "data"
    derived = derive_tz(person.get("phone"), area_map)
    if derived:
        return derived, "area_code_approx"
    return "", "unknown"


UPDATE_FIELDS = ("status", "owner", "relationship")


def apply_account_updates(acct_rows, path, warnings):
    """Overlay input/account-updates.csv (crm-sync's to-book-accounts.csv) on the account
    sources. Non-blank status, owner and relationship values become source values, so
    your own book edits still win, except an open deal: those account ids are returned
    and set to live_deal whatever the book says."""
    rows, _ = read_csv(path)
    by_id = {a["account_id"]: a for a in acct_rows}
    by_crm = {a.get("crm_id", ""): a for a in acct_rows if a.get("crm_id")}
    forced = set()
    for u in rows:
        target = by_id.get(u.get("account_id", "")) or by_crm.get(u.get("crm_id", ""))
        if target is None:
            warnings.append("account update for an unknown account was skipped: "
                            + (u.get("account_id") or u.get("crm_id") or "no id"))
            continue
        for field in UPDATE_FIELDS:
            if u.get(field):
                target[field] = u[field]
        if acct_status(u) == "live_deal":
            forced.add(target["account_id"])
    return forced


def _blocking_strategy(acct, rules):
    """The ladder rules that turn outbound off. None when none match."""
    rel = acct.get("relationship", "")
    status = acct_status(acct)
    if rel == "parent_decides":
        return "hold", "the parent company decides"
    if rel and rel in rules["exclude_relationships"]:
        return "excluded", f"relationship is {rel}"
    if status == "hold":
        return "hold", "account is on hold"
    verdict, reason = icp_fit(acct, rules["icp"])
    if verdict == "out":
        return "hold", f"outside the ICP: {reason}"
    if status == "archived":
        return "hold", "account is archived"
    if status == "live_deal":
        return "live", "a deal is open; the owner leads"
    return None


def acct_status(acct):
    """Account status compared without case or stray spaces ("Live_Deal" is live_deal)."""
    return (acct.get("status") or "").strip().lower().replace(" ", "_")


def strategy_for(acct, people, signals, book, rules):
    """Ordered ladder. The first rule that matches wins. A manual override sticks, but
    never above a rule that turns outbound off (parent decides, excluded, hold, outside
    the ICP, archived, live deal): those still win and say the override was not applied."""
    override = (acct.get("strategy_override") or "").strip()
    blocked = _blocking_strategy(acct, rules)
    if blocked:
        strategy, reason = blocked
        if override and override != strategy:
            reason += f" (override {override} not applied: outbound stays off)"
        return strategy, reason
    if override:
        return override, "manual override"
    acct_tags = set(split_list(acct.get("tags")))
    if acct_tags & set(book["reengage_account_tags"]):
        return "re-engage", "tagged " + ",".join(sorted(acct_tags & set(book["reengage_account_tags"])))
    replied = [p for p in people if set(split_list(p.get("tags"))) & set(book["reengage_person_tags"])]
    if replied:
        return "re-engage", f"{len(replied)} person(s) replied before"
    sig = signals.get(acct["account_id"])
    if sig:
        return "signal", f"playable signal: {sig}"
    if acct.get("tier") in book["priority_tiers"]:
        return "priority", f"tier {acct['tier']}"
    return "automated", "no stronger rule matched"


def load_signals(path):
    rows, _ = read_csv(path)
    out = {}
    for r in rows:
        if r.get("playable", "").lower() in ("yes", "true", "1"):
            out[r.get("account_id", "")] = r.get("top_type") or "signal"
    return out


def build(workspace, out_dir, today, signals_path=None, export_ids=None):
    workspace = Path(workspace)
    out_dir = Path(out_dir)
    input_dir = (workspace / "input").resolve()
    if out_dir.resolve() == input_dir or input_dir in out_dir.resolve().parents:
        raise ValueError("refusing to write into the input folder")
    cfg, gate, book_cfg, personas, lanes, rules = load_config(workspace)

    sources, extra_cols, warnings = [], [], []
    missing_required = [rel for rel in book_cfg.get("required_sources", []) if not (workspace / rel).is_file()]
    if missing_required:
        raise ValueError("required source file missing: " + ", ".join(missing_required)
                         + ". Nothing was written. Add it, or change book.required_sources in gtm.json.")
    for rel in book_cfg["sources"]:
        if not (workspace / rel).is_file():
            warnings.append(f"listed source {rel} is missing and was skipped")
            continue
        rows, cols = read_csv(workspace / rel)
        if rows:
            sources.append((Path(rel).stem, rows))
            extra_cols += [c for c in cols if c not in PEOPLE_COLS + PEOPLE_ADDED and c not in extra_cols]
    if not sources:
        raise ValueError("no source files found; looked for " + ", ".join(book_cfg["sources"]))

    conflicts = []
    merged = merge_sources(sources, conflicts)
    book_rows, book_cols = read_csv(out_dir / "people.csv")
    built_rows, _ = read_csv(out_dir / ".built" / "people.csv")
    extra_cols += [c for c in book_cols if c not in PEOPLE_COLS + PEOPLE_ADDED and c not in extra_cols]
    area_map = book_cfg.get("area_code_tz", {})
    people, built_people_out, adopted = reconcile(merged, book_rows, built_rows, today, conflicts, rules, area_map)

    acct_rows, acct_cols = read_csv(workspace / "input" / "accounts.csv")
    forced_live = apply_account_updates(acct_rows, workspace / "input" / "account-updates.csv", warnings)
    old_accts = {r["account_id"]: r for r in read_csv(out_dir / "accounts.csv")[0]}
    built_accts = {r["account_id"]: r for r in read_csv(out_dir / ".built" / "accounts.csv")[0]}
    accounts = {}
    for a in acct_rows:
        row = dict(a)
        old, last = old_accts.get(a["account_id"]), built_accts.get(a["account_id"], {})
        if old:
            for field in set(old) | set(a):
                if field in COMPUTED_ACCOUNTS or field == "account_id":
                    continue
                if field in ("strategy_override", "pain", "pain_status", "next_step", "tags", "notes"):
                    row[field] = old.get(field, "") or a.get(field, "")
                elif (a["account_id"] not in built_accts and old.get(field, "")) or (
                        a["account_id"] in built_accts and old.get(field, "") != last.get(field, "")):
                    row[field] = old.get(field, "")
                elif not a.get(field):
                    row[field] = old.get(field, "")
        if a["account_id"] in forced_live:
            row["status"] = "live_deal"  # an open deal in the CRM beats any edit: the deal owner leads
        accounts[a["account_id"]] = row
    for aid, old in old_accts.items():
        if aid not in accounts:
            accounts[aid] = dict(old)
    acct_extra = [c for c in acct_cols if c not in ACCOUNT_COLS + ACCOUNT_ADDED]

    by_acct = {}
    for p in people:
        p["persona"], p["lane"], p["role"] = classify(p.get("title"), personas)
        p["timezone"], p["timezone_source"] = time_zone(p, area_map)
        by_acct.setdefault(p.get("account_id", ""), []).append(p)

    # Strategy first: the send and call gates read it.
    signals = load_signals(Path(signals_path) if signals_path else workspace / "signals" / "scored.csv")
    for aid, a in accounts.items():
        a["strategy"], a["strategy_reason"] = strategy_for(a, by_acct.get(aid, []), signals,
                                                           book_cfg, rules)
    for p in people:
        acct = accounts.get(p.get("account_id", ""), {})
        p["send_ok"], p["send_block_reason"] = first_touch_gate(p, acct, gate, rules)
        p["followup_ok"], p["followup_block_reason"] = followup_gate(
            p, acct, gate, rules, by_acct.get(p.get("account_id", ""), []), book_cfg["reply_tags"])
        p["call_ok"], p["call_block_reason"] = call_gate(p, acct, rules)
        p["linkedin_ok"], p["linkedin_block_reason"] = linkedin_gate(p, acct, rules)

    for aid, a in accounts.items():
        group = by_acct.get(aid, [])
        buying = [p for p in group if p["persona"]]
        ok = [p for p in buying if p["send_ok"] == "yes"]
        covered = [l for l in lanes if any(p["lane"] == l for p in buying)]
        a["people_count"] = str(len(group))
        a["buying_group_count"] = str(len(buying))
        a["send_ok_count"] = str(len(ok))
        roles_ok = all(any(p["role"] == r for p in ok) for r in book_cfg.get("ready_requires_roles") or [])
        if len(ok) >= int(book_cfg["ready_min"]) and roles_ok:
            a["readiness"] = "ready"
        elif buying:
            a["readiness"] = "enrich"
        else:
            a["readiness"] = "prospect"
        a["lanes_covered"] = ";".join(covered)
        a["lanes_missing"] = ";".join(l for l in lanes if l not in covered)
        if not a.get("pain_status"):
            a["pain_status"] = "hypothesis"

    people.sort(key=lambda r: (r.get("account_id", ""), r.get("last_name", "").lower(), r["person_id"]))
    acct_list = sorted(accounts.values(), key=lambda r: r["account_id"])
    p_cols = PEOPLE_COLS + PEOPLE_ADDED + extra_cols
    a_cols = ACCOUNT_COLS + ACCOUNT_ADDED + acct_extra

    snapshot, _ = read_csv(workspace / "input" / "crm-snapshot.csv")
    fixes = crm_fixes(people, snapshot, book_cfg["fix_fields"])

    write_csv(out_dir / "people.csv", people, p_cols)
    write_csv(out_dir / "accounts.csv", acct_list, a_cols)
    # .built keeps the merged SOURCE values, not the book. A user edit is any book
    # value that differs from them, so edits survive every later rebuild.
    built_cols = PEOPLE_COLS + [c for c in extra_cols if c not in PEOPLE_ADDED]
    built_people_out.sort(key=lambda r: r["person_id"])
    write_csv(out_dir / ".built" / "people.csv", built_people_out, built_cols)
    built_accts_out = []
    for a in acct_rows:
        saved = dict(a)
        for f, v in built_accts.get(a["account_id"], {}).items():
            if v and not saved.get(f):
                saved[f] = v  # a blank source keeps its last value
        built_accts_out.append(saved)
    write_csv(out_dir / ".built" / "accounts.csv", sorted(built_accts_out, key=lambda r: r["account_id"]),
              ACCOUNT_COLS + acct_extra)
    write_csv(out_dir / "fixes.csv", fixes, ["person_id", "crm_id", "field", "crm_value", "book_value"])
    write_csv(out_dir / "conflicts.csv", conflicts,
              ["person_id", "field", "book_value", "source_value", "source", "note"])
    (out_dir / "accounts.md").write_text(summary_md(acct_list, today), encoding="utf-8")

    result = {"people": len(people), "accounts": len(acct_list), "fixes": len(fixes),
              "conflicts": len(conflicts),
              "send_ok": sum(p["send_ok"] == "yes" for p in people),
              "no_crm_id": sum(not p.get("crm_id") for p in people),
              "manual": sum("manual" in split_list(p.get("source")) for p in people),
              "ids_adopted": len(adopted),
              "warnings": warnings}
    if export_ids:
        result.update(export(people, accounts, export_ids, out_dir, p_cols))
    return result


def crm_fixes(people, snapshot, fields):
    index = Index()
    snap = {}
    for i, r in enumerate(snapshot):
        key = str(i)
        snap[key] = r
        probe = {k: v for k, v in r.items() if k != "person_id"}
        index.add(key, probe)
    out = []
    for p in people:
        probe = {"crm_id": p.get("crm_id", ""), "email": p.get("email", ""),
                 "first_name": p.get("first_name", ""), "last_name": p.get("last_name", ""),
                 "account_id": p.get("account_id", "")}
        key, _ = index.find(probe)
        if key is None:
            continue
        crm = snap[key]
        for f in fields:
            if p.get(f) and p.get(f) != crm.get(f, ""):
                out.append({"person_id": p["person_id"], "crm_id": p.get("crm_id") or crm.get("crm_id", ""),
                            "field": f, "crm_value": crm.get(f, ""), "book_value": p[f]})
    return out


def export(people, accounts, ids, out_dir, cols):
    wanted = set(ids)
    known = set(accounts) if isinstance(accounts, dict) else {a.get("account_id") for a in accounts}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError("--export names account ids not in the book: " + ", ".join(unknown))
    keep, left = [], []
    for p in people:
        if p.get("account_id") not in wanted:
            continue
        if p["send_ok"] != "yes":
            left.append(dict(p, left_out_reason=p["send_block_reason"]))
        else:
            keep.append(p)
    write_csv(out_dir / "export.csv", keep, cols)
    write_csv(out_dir / "export-left-out.csv", left,
              ["person_id", "account_id", "first_name", "last_name", "title", "left_out_reason"])
    return {"exported": len(keep), "left_out": len(left)}


def summary_md(accounts, today):
    lines = [f"# Account Book ({today})", "",
             "| Account | Strategy | Why | Readiness | Send-ready | Lanes missing |",
             "|---|---|---|---|---|---|"]
    for a in accounts:
        lines.append(f"| {a.get('name', a['account_id'])} | {a['strategy']} | {a['strategy_reason']} | "
                     f"{a['readiness']} | {a['send_ok_count']} | {a['lanes_missing'] or 'none'} |")
    lines += ["", "Pain lines stay a hypothesis until someone hears them on a call.", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default="gtm")
    ap.add_argument("--out", help="book folder (default: <workspace>/book)")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD, used to date new notes")
    ap.add_argument("--signals", help="scored signals CSV (default: <workspace>/signals/scored.csv)")
    ap.add_argument("--export", help="comma-separated account ids to export send-ready people for")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.today):
        ap.error("--today must be YYYY-MM-DD")
    out = Path(args.out) if args.out else Path(args.workspace) / "book"
    ids = [x.strip() for x in args.export.split(",") if x.strip()] if args.export else None
    try:
        res = build(args.workspace, out, args.today, args.signals, ids)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Book written to {out}")
    for k, v in res.items():
        if k != "warnings":
            print(f"  {k}: {v}")
    for w in res.get("warnings", []):
        print(f"Warning: {w}")
    print("Nothing was sent or written to any CRM. fixes.csv lists changes for you to make there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
