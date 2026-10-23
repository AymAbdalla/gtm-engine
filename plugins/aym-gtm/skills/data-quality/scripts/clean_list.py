#!/usr/bin/env python3
"""Clean a people list into ready, later, review, enrich and quarantine files.

Reads gtm.json, input/people.csv and input/accounts.csv from a GTM workspace.
Writes only to --out (default <workspace>/clean). Never edits an input file,
never calls a vendor and never writes to a CRM.

Every person lands in exactly one file, with a reason:
  ready.csv       usable now, ranked by score, capped per account
  later.csv       usable, but over the per-account cap
  review.csv      a person must decide (soft title, duplicate, missing account)
  enrich.csv      worth fixing first (no channel, identity doubt, no title)
  quarantine.csv  screened out (do-not-contact, not a buyer, out of ICP)
"""
import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtm_fit import fit as icp_fit  # noqa: E402  (shared ICP-fit rule, copied in four skills)

DEFAULTS = {
    "icp": {
        "size": {"min": 200, "max": 2000, "sweet_min": 300, "sweet_max": 1000},
        "countries": [],
        "industries_in": [],
        "industries_out": [],
        "exclude_relationships": ["competitor", "customer", "partner", "parent_decides"],
    },
    "region_title_rule": {
        "other_region_words": ["emea", "apac", "latam", "europe", "asia", "anz", "dach", "uk"],
        "senior_exempt_patterns": ["chief", r"\bvp\b", "vice president", r"\bhead of\b", r"\bcfo\b", r"\bcio\b"],
    },
    "personas": [],
    "not_buyer_titles": [r"\bintern\b", "student", "recruit", "sales rep", "account executive"],
    "review_titles": ["consultant", "advisor", "founder"],
    "freemail_domains": ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                         "icloud.com", "aol.com", "proton.me", "protonmail.com"],
    "stop_statuses": ["hold", "booked", "not_interested", "wrong_person", "left",
                      "do_not_contact", "archived"],
    "dnc_tags": ["opted_out", "dnc_all"],
    "left_tags": ["moved"],
    "channel_block_tags": {"email": ["bounced"], "call": ["dnc_phone", "phone_failed"], "linkedin": []},
    "clean": {
        "cap_per_account": 3,
        "stale_touch_days": 365,
        "phone_points": {"direct": 30, "switchboard": 10, "international": 5,
                         "toll_free": 0, "malformed": 0, "none": 0},
        "persona_multiplier": 3,
        "size_points": {"sweet": 10, "band": 5},
        "never_touched_bonus": 5,
        "defect_penalty": 10,
        "dnc_phone_penalty": 40,
        "tier_points": {"P1": 3, "P2": 2, "P3": 1},
        "home_country_codes": ["1"],
        "toll_free_area_codes": ["800", "833", "844", "855", "866", "877", "888"],
        "dnc_note_patterns": ["do not contact", "don't contact", "not to contact",
                              "unsubscribe", "remove me", "stop emailing"],
    },
}

ADDED = ["account_name", "persona", "lane", "role", "phone_type", "channels",
         "defects", "score", "score_detail", "reason"]
BUCKETS = ("ready", "later", "review", "enrich", "quarantine")


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
    cfg = deep_merge(DEFAULTS, data)
    if not cfg["personas"]:
        raise SystemExit("gtm.json has no personas. Run icp-define first, or add a personas list.")
    for persona in cfg["personas"]:
        persona["_rx"] = [re.compile(p, re.I) for p in persona.get("title_patterns", [])]
    cfg["_not_buyer"] = [re.compile(p, re.I) for p in cfg["not_buyer_titles"]]
    cfg["_review"] = [re.compile(p, re.I) for p in cfg["review_titles"]]
    cfg["_senior"] = [re.compile(p, re.I) for p in cfg["region_title_rule"]["senior_exempt_patterns"]]
    return cfg


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_list(value):
    return [v.strip().lower() for v in (value or "").split(";") if v.strip()]


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


# LinkedIn member ids look like ACoAA... or ACwAA..., case-sensitive. A name slug such as
# acosta-maria must not match, or it would skip the name check.
LINKEDIN_ID = re.compile(r"^AC[a-zA-Z]AA[A-Za-z0-9_-]{4,}$")


def linkedin_id_link(url):
    """True for a profile link that carries an id, not a name: Sales Navigator lead links
    and /in/ACwAA... style ids. The name check cannot judge those."""
    if "/sales/" in url.lower():
        return True
    slug = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return bool(LINKEDIN_ID.match(slug))


def phone_key(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else ""


def norm_name(first, last):
    return re.sub(r"[^a-z]", "", (first or "").lower()) + "|" + re.sub(r"[^a-z]", "", (last or "").lower())


def phone_type(raw, cfg):
    """Label a phone number by its format. The rules assume a +1 home market."""
    clean = cfg["clean"]
    text = (raw or "").strip()
    if not text:
        return "none"
    text = re.sub(r"(?i)\s*(x|ext\.?)\s*\d+$", "", text)
    if re.search(r"[A-Za-z]", text):
        return "malformed"
    digits = re.sub(r"\D", "", text)
    international = text.startswith("+") or text.startswith("00")
    if text.startswith("00"):
        digits = digits[2:]
    home = clean["home_country_codes"]
    if international:
        if "1" in home and digits.startswith("1") and len(digits) == 11:
            local = digits[1:]
        elif any(digits.startswith(c) for c in home if c != "1"):
            return "direct" if 8 <= len(digits) <= 15 else "malformed"
        else:
            return "international" if 8 <= len(digits) <= 15 else "malformed"
    elif len(digits) == 11 and digits.startswith("1"):
        local = digits[1:]
    elif len(digits) == 10:
        local = digits
    else:
        return "malformed"
    if local[:3] in clean["toll_free_area_codes"]:
        return "toll_free"
    if local.endswith("00"):
        return "switchboard"
    return "direct"


def account_domains(account):
    domains = [(account.get("domain") or "").strip().lower()]
    domains += split_list(account.get("other_domains"))
    return {d for d in domains if d}


def icp_fit_check(account, cfg):
    """(verdict, reason) from the shared fit rule. An archived account is out too."""
    if (account.get("status") or "").strip().lower() == "archived":
        return "out", "account archived"
    return icp_fit(account, cfg["icp"])


def size_band(account, cfg):
    size = to_int(account.get("employees"))
    band = cfg["icp"]["size"]
    if size is None:
        return "unknown"
    if band["sweet_min"] <= size <= band["sweet_max"]:
        return "sweet"
    if band["min"] <= size <= band["max"]:
        return "band"
    return "outside"


def match_persona(title, cfg):
    for persona in cfg["personas"]:
        if any(rx.search(title) for rx in persona["_rx"]):
            return persona
    return None


def stop_kind(person, cfg):
    """Why this record must not be contacted on any channel, as (kind, reason).

    kind is "dnc" (the person asked not to be contacted: status do_not_contact,
    an opt-out tag or a do-not-contact note), "left" (status left or a left tag),
    or "status" (any other stop status, such as booked or hold). Empty kind means
    no stop."""
    status = (person.get("status") or "").strip().lower()
    tags = split_list(person.get("tags"))
    if status == "do_not_contact":
        return "dnc", "person status is do_not_contact"
    hit = [t for t in tags if t in cfg["dnc_tags"]]
    if hit:
        return "dnc", f"opt-out tag {hit[0]}"
    notes = (person.get("notes") or "").lower()
    phrase = next((p for p in cfg["clean"]["dnc_note_patterns"] if p in notes), "")
    if phrase:
        return "dnc", f"notes say '{phrase}': record it as do_not_contact"
    if status == "left":
        return "left", "person status is left"
    hit = [t for t in tags if t in cfg.get("left_tags", [])]
    if hit:
        return "left", f"tag {hit[0]}: person may have left (set status left if true)"
    if status in cfg["stop_statuses"]:
        return "status", f"person status is {status}"
    return "", ""


def stop_reason(person, cfg):
    """Why this record must never be contacted on any channel. Empty means no stop."""
    return stop_kind(person, cfg)[1]


def classify(person, account, cfg, today):
    """Return (bucket, reason, extras) for one person. Pure function."""
    clean = cfg["clean"]
    extras = {k: "" for k in ADDED}
    extras["account_name"] = account.get("name", "") if account else ""
    tags = split_list(person.get("tags"))
    title = (person.get("title") or "").strip()

    # 1. Screens: do-not-contact always wins.
    stop = stop_reason(person, cfg)
    if stop:
        return "quarantine", stop, extras
    fit_verdict, fit_reason = icp_fit_check(account, cfg)
    if fit_verdict == "out":
        return "quarantine", "account out of ICP: " + fit_reason, extras
    country = (person.get("country") or "").strip().upper()
    icp_countries = [c.upper() for c in cfg["icp"]["countries"]]
    if icp_countries and country and country not in icp_countries:
        return "quarantine", f"person country {country} outside ICP", extras

    # 2. Title ladder. Hard not-buyer beats any persona match.
    if not title:
        return "enrich", "no title: find it before scoring", extras
    if any(rx.search(title) for rx in cfg["_not_buyer"]):
        return "quarantine", f"title is never a buyer ({title})", extras
    persona = match_persona(title, cfg)
    if persona is None:
        if any(rx.search(title) for rx in cfg["_review"]):
            return "review", f"title needs a human look ({title})", extras
        return "quarantine", f"title matches no target persona ({title})", extras
    senior = any(rx.search(title) for rx in cfg["_senior"])
    region_terms = cfg["region_title_rule"]["other_region_words"]
    region = next((t for t in region_terms if re.search(rf"\b{re.escape(t)}\b", title.lower())), "")
    if region and not senior:
        return "quarantine", f"title names another region ({region}) and is not senior", extras
    extras.update(persona=persona["id"], lane=persona.get("lane", ""), role=persona.get("role", ""))
    if fit_verdict == "unknown":
        return "enrich", "account fit unknown: " + fit_reason, extras

    # 3. Channels and defects.
    defects = []
    ptype = phone_type(person.get("phone"), cfg)
    extras["phone_type"] = ptype
    email_blocks = [t for t in tags if t in cfg["channel_block_tags"].get("email", [])]
    call_blocks = [t for t in tags if t in cfg["channel_block_tags"].get("call", [])]
    dnc_phone = bool(call_blocks)
    if dnc_phone and person.get("phone"):
        defects.append("dnc_phone")
    if ptype in ("international", "toll_free", "malformed"):
        defects.append(f"phone_{ptype}")
    email = (person.get("email") or "").strip().lower()
    email_status = (person.get("email_status") or "").strip().lower()
    domains = account_domains(account)
    email_domain = email.split("@")[-1] if "@" in email else ""
    identity_doubt = []
    if email and email_status == "invalid":
        defects.append("email_invalid")
    if email and email_blocks:
        defects.append("email_" + email_blocks[0])
    if email_status == "catch_all":
        defects.append("catch_all_email")
    if email_domain and email_domain in cfg["freemail_domains"]:
        defects.append("personal_email")
        identity_doubt.append("personal email, not a work address")
    elif email_domain and domains and email_domain not in domains:
        defects.append("email_domain_mismatch")
        identity_doubt.append(f"email domain {email_domain} is not on the account")
    url = (person.get("linkedin_url") or "").strip()
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    last = re.sub(r"[^a-z]", "", (person.get("last_name") or "").lower())
    if slug and last and not linkedin_id_link(url) and last not in re.sub(r"[^a-z]", "", slug):
        defects.append("profile_mismatch")
        identity_doubt.append("profile URL may name a different person")
    touched = parse_date(person.get("last_touch_date"))
    if touched and (today - touched).days > clean["stale_touch_days"]:
        defects.append("stale_touch")
    if "vendor_no_record" in tags:
        defects.append("vendor_no_record")

    email_ok = bool(email) and email_status != "invalid" and not email_blocks
    phone_ok = ptype in ("direct", "switchboard") and not dnc_phone
    channels = [c for c, ok in (("email", email_ok), ("phone", phone_ok),
                                ("linkedin", bool(slug))) if ok]
    extras["channels"] = ";".join(channels)
    extras["defects"] = ";".join(defects)

    # 4. Score: phone type matters most, then persona, size, freshness.
    # Each part is listed in score_detail so a person can check it and change the weights.
    band = size_band(account, cfg)
    parts = [("phone " + ptype, 0 if dnc_phone else clean["phone_points"].get(ptype, 0)),
             ("persona", persona.get("points", 0) * clean["persona_multiplier"]),
             ("size " + str(band), clean["size_points"].get(band, 0))]
    if not touched:
        parts.append(("never touched", clean["never_touched_bonus"]))
    real_defects = len([d for d in defects if d != "dnc_phone"])
    if real_defects:
        parts.append(("defects x" + str(real_defects), -clean["defect_penalty"] * real_defects))
    if dnc_phone:
        parts.append(("do-not-call phone", -clean["dnc_phone_penalty"]))
    score = sum(v for _, v in parts)
    extras["score"] = str(score)
    extras["score_detail"] = "; ".join(f"{name} {value:+g}" for name, value in parts)

    if identity_doubt:
        return "enrich", "identity doubt: " + "; ".join(identity_doubt), extras
    if not (email_ok or phone_ok):
        return "enrich", "no usable email or phone", extras
    return "ready", "ready: " + ", ".join(channels), extras


def account_value(account, cfg):
    tier = (account.get("tier") or "").strip().upper()
    value = cfg["clean"]["tier_points"].get(tier, 0)
    return value + (2 if size_band(account, cfg) == "sweet" else 0)


def person_keys(person):
    """The ways two rows can be the same person: id, email, name at the same account."""
    keys = []
    pid = (person.get("person_id") or "").strip()
    if pid:
        keys.append(("id", pid))
    email = (person.get("email") or "").strip().lower()
    if email:
        keys.append(("email", email))
    name = norm_name(person.get("first_name"), person.get("last_name"))
    if name != "|":
        keys.append(("name", name, person.get("account_id", "")))
    return keys


def run(cfg, people, accounts, today, cap=None):
    """Classify every person. Returns {bucket: [rows]}."""
    cap = cfg["clean"]["cap_per_account"] if cap is None else cap
    by_account = {a.get("account_id", ""): a for a in accounts}
    out = {b: [] for b in BUCKETS}
    # Do-not-contact wins before duplicates are judged. If any row of a person
    # asked not to be contacted or has left, every row that shares an id, email or
    # name+account is quarantined too. Another stop status on a linked row (booked,
    # hold) only sends the other rows to review: the stale row may be the wrong one.
    stops = {}
    rank = {"dnc": 0, "left": 1, "status": 2}
    for idx, person in enumerate(people):
        kind, why = stop_kind(person, cfg)
        if kind:
            for key in person_keys(person):
                prev = stops.get(key)
                if prev is None or rank[kind] < rank[prev[0]]:
                    stops[key] = (kind, person.get("person_id", ""), why, idx)
    seen_id, seen_email, seen_name, seen_phone = {}, {}, {}, {}
    for idx, person in enumerate(people):
        pid = person.get("person_id", "")
        email = (person.get("email") or "").strip().lower()
        name_key = (norm_name(person.get("first_name"), person.get("last_name")), person.get("account_id", ""))
        last_norm = re.sub(r"[^a-z]", "", (person.get("last_name") or "").lower())
        phone_digits = phone_key(person.get("phone"))
        phone_key_val = (phone_digits, last_norm, person.get("account_id", "")) if phone_digits and last_norm else None
        linked = None
        for k in person_keys(person):
            if k in stops and stops[k][3] != idx and (linked is None or rank[stops[k][0]] < rank[linked[0]]):
                linked = stops[k]
        dup = ""
        if pid and pid in seen_id:
            dup = f"duplicate of {seen_id[pid]} (same person_id)"
        elif email and email in seen_email:
            dup = f"duplicate of {seen_email[email]} (same email)"
        elif name_key[0] != "|" and name_key in seen_name:
            dup = f"possible duplicate of {seen_name[name_key]} (same name at same account)"
        elif phone_key_val and phone_key_val in seen_phone:
            dup = f"possible duplicate of {seen_phone[phone_key_val]} (same phone and last name at same account)"
        seen_id.setdefault(pid, pid)
        if email:
            seen_email.setdefault(email, pid)
        seen_name.setdefault(name_key, pid)
        if phone_key_val:
            seen_phone.setdefault(phone_key_val, pid)
        account = by_account.get(person.get("account_id", ""))
        own_stop = stop_reason(person, cfg)
        if own_stop or (linked and linked[0] in ("dnc", "left")):
            extras = {k: "" for k in ADDED}
            extras["account_name"] = account.get("name", "") if account else ""
            if own_stop:
                reason = own_stop
            elif linked[0] == "dnc":
                reason = f"linked record {linked[1]} is do-not-contact ({linked[2]})"
            else:
                reason = f"linked record {linked[1]}: {linked[2]}"
            bucket = "quarantine"
        elif linked:
            bucket, extras = "review", {k: "" for k in ADDED}
            reason = f"linked record {linked[1]}: {linked[2]}; check which record is current before contacting"
        elif dup:
            bucket, reason, extras = "review", dup, {k: "" for k in ADDED}
        elif account is None:
            bucket, reason, extras = "review", "account_id not found in accounts file", {k: "" for k in ADDED}
        else:
            bucket, reason, extras = classify(person, account, cfg, today)
        row = dict(person)
        row.update(extras)
        row["reason"] = reason
        row["_value"] = account_value(account, cfg) if account else 0
        out[bucket].append(row)

    def score(row):
        return to_int(row.get("score")) or 0

    ranked = sorted(out["ready"], key=lambda r: (-score(r), r.get("person_id", "")))
    counts, ready, later = {}, [], []
    for row in ranked:
        acct = row.get("account_id", "")
        counts[acct] = counts.get(acct, 0) + 1
        if counts[acct] <= cap:
            ready.append(row)
        else:
            row["reason"] = f"over the per-account cap of {cap}; use when a seat frees up"
            later.append(row)
    out["ready"], out["later"] = ready, later
    out["enrich"].sort(key=lambda r: (-r["_value"], -score(r), r.get("person_id", "")))
    for bucket in ("review", "quarantine"):
        out[bucket].sort(key=lambda r: (r.get("account_id", ""), r.get("person_id", "")))
    return out


def report(out, today):
    lines = [f"# List clean report ({today.isoformat()})", "",
             "| File | People |", "|---|---|"]
    for bucket in BUCKETS:
        lines.append(f"| {bucket}.csv | {len(out[bucket])} |")
    for bucket in ("quarantine", "review", "enrich"):
        reasons = {}
        for row in out[bucket]:
            key = row["reason"].split(":")[0].split("(")[0].strip()
            reasons[key] = reasons.get(key, 0) + 1
        if reasons:
            lines += ["", f"## {bucket} reasons", ""]
            lines += [f"- {k}: {v}" for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))]
    lines += ["", "Notes:",
              "- ready means the data is usable. account-book's send gate decides who may be emailed.",
              "- A vendor with no record of a person is not proof they left. Verify before dropping.",
              "- Nothing was sent and no CRM record was changed. These are files for you to review."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--workspace", default="gtm")
    parser.add_argument("--config", help="default <workspace>/gtm.json")
    parser.add_argument("--people", help="default <workspace>/input/people.csv")
    parser.add_argument("--accounts", help="default <workspace>/input/accounts.csv")
    parser.add_argument("--out", help="default <workspace>/clean")
    parser.add_argument("--today", help="YYYY-MM-DD, default today")
    parser.add_argument("--cap", type=int, help="people per account in ready.csv")
    args = parser.parse_args(argv)
    ws = Path(args.workspace)
    config = Path(args.config or ws / "gtm.json")
    people_path = Path(args.people or ws / "input" / "people.csv")
    accounts_path = Path(args.accounts or ws / "input" / "accounts.csv")
    out_dir = Path(args.out or ws / "clean")
    today = date.fromisoformat(args.today) if args.today else date.today()
    inputs = {p.resolve() for p in (config, people_path, accounts_path)}
    input_dirs = {p.resolve().parent for p in (people_path, accounts_path)}
    targets = [out_dir / f"{b}.csv" for b in BUCKETS] + [out_dir / "report.md"]
    if out_dir.resolve() in input_dirs or any(t.resolve() in inputs for t in targets):
        raise SystemExit("refusing to write into the input folder; choose another --out")
    cfg = load_config(config)
    header, people = read_csv(people_path)
    _, accounts = read_csv(accounts_path)
    out = run(cfg, people, accounts, today, args.cap)
    out_dir.mkdir(parents=True, exist_ok=True)
    full = header + [c for c in ADDED if c not in header]
    for bucket in BUCKETS:
        write_csv(out_dir / f"{bucket}.csv", full, out[bucket])
    text = report(out, today)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
