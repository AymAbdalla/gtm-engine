#!/usr/bin/env python3
"""Score dated buying signals per account and write a why-now line for each.

Reads raw signal CSVs from <workspace>/signals/raw/<YYYY-MM-DD>/ and never
changes them. When the same signal id appears in more than one pull, the
newest dated pull wins (a skipped row never blocks a later corrected one).
Matches each signal to an account (domain first, then exact
normalized name), drops expired signals, scores each account as the sum of
each signal type's best weight x recency factor, applies the playable gate,
and writes:

  <out>/scored.csv   one row per account that has at least one matched signal
  <out>/signals.csv  every raw row with its status, so any score can be traced
  <out>/report.md    a short readable summary

Standard library only. No network. Never sends anything.
"""

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtm_fit import fit as icp_fit  # noqa: E402  (shared ICP-fit rule, copied in four skills)

DEFAULT_TYPES = {
    "new_leader": {"weight": 5, "expires_days": 180, "seat": "the named new leader",
                   "watch": "a new leader in the buying team"},
    "leader_gap": {"weight": 4, "expires_days": 180,
                   "seat": "the most senior remaining leader, never the person who left",
                   "watch": "a leader leaving the buying team"},
    "hiring": {"weight": 4, "expires_days": 60, "seat": "the likely manager of the open role",
               "watch": "a job post for a role your product helps"},
    "funding": {"weight": 4, "expires_days": 365, "seat": "decision maker",
                "watch": "a funding round or acquisition"},
    "topic_intent": {"weight": 3, "expires_days": 30, "seat": "decision maker",
                     "watch": "research interest in your topic"},
    "growth": {"weight": 2, "expires_days": 180, "seat": "decision maker",
               "watch": "a new office, site or team"},
    "layoffs": {"weight": 0, "expires_days": 180, "seat": "context only",
                "watch": "layoffs (context only, never a reason to reach out)"},
}
DEFAULT_RECENCY = [[30, 1.0], [90, 0.7], [100000, 0.4]]
DEFAULT_BLOCKED_STATUS = ["hold", "live_deal", "archived"]
DEFAULT_BLOCKED_RELATIONSHIPS = ["competitor", "customer", "partner", "parent_decides"]
ALWAYS_BLOCKED_RELATIONSHIPS = ["parent_decides"]
TIMING_ONLY_TYPES = ["topic_intent"]

RAW_COLUMNS = ["signal_id", "account_name", "domain", "type", "event_date", "summary",
               "source_url", "person_name", "person_title"]
SCORED_COLUMNS = ["account_id", "name", "score", "top_type", "playable", "why_not", "why_now",
                  "source_url", "event_date", "seat", "live_signals", "signals", "check", "quadrant"]
TRACE_COLUMNS = ["raw_file", "signal_id", "account_name", "domain", "type", "event_date",
                 "summary", "source_url", "person_name", "person_title", "status", "reason",
                 "account_id", "age_days", "weight", "recency", "value", "check"]
LEGAL_SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co",
                  "company", "plc", "gmbh", "lp", "llp", "sa", "ag", "pllc", "pc"}


class ConfigError(ValueError):
    pass


def parse_date(text):
    try:
        return dt.date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def load_config(path):
    """Return the signals settings, with defaults for anything missing."""
    raw = {}
    if path and Path(path).is_file():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    section = raw.get("signals", {}) if isinstance(raw, dict) else {}
    icp = raw.get("icp", {}) if isinstance(raw, dict) else {}
    types = {k: dict(v) for k, v in DEFAULT_TYPES.items()}
    for name, spec in (section.get("types") or {}).items():
        merged = dict(types.get(name, {"seat": "decision maker", "watch": name.replace("_", " ")}))
        merged.update(spec or {})
        types[name] = merged
    for name, spec in types.items():
        weight, days = spec.get("weight"), spec.get("expires_days")
        if not isinstance(weight, (int, float)) or weight < 0:
            raise ConfigError(f"signals.types.{name}.weight must be a number 0 or more")
        if not isinstance(days, int) or days <= 0:
            raise ConfigError(f"signals.types.{name}.expires_days must be a whole number above 0")
    recency = section.get("recency", DEFAULT_RECENCY)
    last = -1
    for band in recency:
        if (not isinstance(band, list) or len(band) != 2 or not isinstance(band[0], int)
                or not isinstance(band[1], (int, float)) or not 0 <= band[1] <= 1 or band[0] <= last):
            raise ConfigError("signals.recency must be [[max_age_days, factor], ...] with days "
                              "increasing and factors between 0 and 1")
        last = band[0]
    return {
        "types": types,
        "recency": recency,
        "blocked_status": section.get("blocked_status", DEFAULT_BLOCKED_STATUS),
        "blocked_relationships": blocked_relationships(section, icp),
        "timing_only": section.get("timing_only_types", TIMING_ONLY_TYPES),
        "icp": icp if isinstance(icp, dict) else {},
    }


def blocked_relationships(section, icp):
    """Relationships that are never playable: signals.blocked_relationships if set, else the
    ICP's exclude_relationships, else the defaults. parent_decides is always blocked."""
    chosen = section.get("blocked_relationships")
    if chosen is None:
        chosen = icp.get("exclude_relationships") if isinstance(icp, dict) else None
    if chosen is None:
        chosen = DEFAULT_BLOCKED_RELATIONSHIPS
    out = [str(r).strip().lower() for r in chosen]
    for r in ALWAYS_BLOCKED_RELATIONSHIPS:
        if r not in out:
            out.append(r)
    return out


def recency_factor(age_days, table):
    for max_days, factor in table:
        if age_days <= max_days:
            return float(factor)
    return 0.0


def normalize_domain(text):
    d = (text or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/")[0].split("?")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def normalize_name(text):
    words = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower().replace("&", " and ")).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_indexes(accounts):
    by_domain, by_name = {}, {}
    for acc in accounts:
        aid = acc.get("account_id", "").strip()
        domains = [acc.get("domain", "")] + (acc.get("other_domains", "") or "").split(";")
        for d in {normalize_domain(x) for x in domains if x.strip()}:
            by_domain.setdefault(d, set()).add(aid)
        key = normalize_name(acc.get("name", ""))
        if key:
            by_name.setdefault(key, set()).add(aid)
    return by_domain, by_name


def match_account(row, by_domain, by_name):
    """Return (account_id, reason). Domain first, then exact normalized name. Never fuzzy."""
    domain = normalize_domain(row.get("domain", ""))
    if domain and domain in by_domain:
        hits = by_domain[domain]
        if len(hits) == 1:
            return next(iter(hits)), "domain"
        return None, "domain matches more than one account"
    key = normalize_name(row.get("account_name", ""))
    if key and key in by_name:
        hits = by_name[key]
        if len(hits) == 1:
            return next(iter(hits)), "name"
        return None, "name matches more than one account"
    return None, "no account with this domain or name"


def raw_files(raw_root, today):
    files, skipped_folders = [], []
    if not raw_root.is_dir():
        return files, skipped_folders
    for folder in sorted(p for p in raw_root.iterdir() if p.is_dir()):
        pulled = parse_date(folder.name)
        if pulled is None or pulled > today:
            skipped_folders.append(folder.name)
            continue
        files.extend(sorted(folder.glob("*.csv")))
    return files, skipped_folders


def why_now_sentence(sig):
    summary = re.sub(r"\s+", " ", sig["summary"].strip()).rstrip(".")
    return f"{summary} (source dated {sig['event_date']})."


def score(workspace, today, accounts_path=None, out_dir=None, config_path=None):
    workspace = Path(workspace)
    raw_root = workspace / "signals" / "raw"
    accounts_path = Path(accounts_path) if accounts_path else workspace / "input" / "accounts.csv"
    out_dir = Path(out_dir) if out_dir else workspace / "signals"
    config_path = Path(config_path) if config_path else workspace / "gtm.json"
    if out_dir.resolve() == raw_root.resolve() or raw_root.resolve() in out_dir.resolve().parents:
        raise ValueError("refusing to write inside signals/raw; raw pulls stay untouched")
    if not accounts_path.is_file():
        raise ValueError(f"accounts file not found: {accounts_path}")
    cfg = load_config(config_path)
    accounts = read_csv(accounts_path)
    acc_by_id = {a["account_id"].strip(): a for a in accounts if a.get("account_id", "").strip()}
    by_domain, by_name = build_indexes(accounts)
    files, skipped_folders = raw_files(raw_root, today)

    trace = []
    per_account = {}
    counts = {"read": 0, "live": 0, "expired": 0, "unmatched": 0, "skipped": 0, "duplicate": 0}

    # Pass 1: read every row and decide the problems that do not depend on other rows.
    for path in files:
        rel = path.relative_to(workspace).as_posix()
        pull = path.parent.name
        for row in read_csv(path):
            counts["read"] += 1
            rec = {c: (row.get(c) or "").strip() for c in RAW_COLUMNS}
            rec.update(raw_file=rel, status="", reason="", account_id="", age_days="",
                       weight="", recency="", value="", check="")
            rec["_pull"] = pull
            rec["_key"] = rec["signal_id"] or "|".join([
                normalize_domain(rec["domain"]) or normalize_name(rec["account_name"]),
                rec["type"], rec["event_date"], rec["source_url"]])
            event = parse_date(rec["event_date"])
            rec["_event"] = event
            if rec["type"] not in cfg["types"]:
                rec.update(status="skipped", reason=f"unknown type {rec['type']!r}")
            elif event is None:
                rec.update(status="skipped", reason="no valid event date; signals must be dated")
            elif event > today:
                rec.update(status="skipped", reason="event date is after today")
            elif not rec["source_url"]:
                rec.update(status="skipped", reason="no source link; facts need a source")
            trace.append(rec)

    # Pass 2: one usable row per signal. The newest pull wins; within one pull the first row wins.
    # Skipped rows never block a later corrected row.
    winner = {}
    for rec in trace:
        if rec["status"]:
            continue
        best = winner.get(rec["_key"])
        if best is None or rec["_pull"] > best["_pull"]:
            winner[rec["_key"]] = rec
    for rec in trace:
        if rec["status"]:
            continue
        best = winner[rec["_key"]]
        if rec is not best:
            if rec["_pull"] == best["_pull"]:
                rec.update(status="duplicate", reason="same signal already read in this pull")
            else:
                rec.update(status="duplicate", reason=f"replaced by the newer pull {best['_pull']}")
    # A skipped row that a newer pull corrected is replaced, not a problem to fix.
    for rec in trace:
        best = winner.get(rec["_key"])
        if rec["status"] == "skipped" and best is not None and best["_pull"] > rec["_pull"]:
            rec.update(status="duplicate",
                       reason=f"replaced by the newer pull {best['_pull']} (was skipped: {rec['reason']})")

    # Pass 3: match and score the winning rows.
    for rec in trace:
        if not rec["status"]:
            aid, how = match_account(rec, by_domain, by_name)
            spec = cfg["types"][rec["type"]]
            age = (today - rec["_event"]).days
            rec["age_days"] = age
            if aid is not None and how == "domain":
                signal_name = normalize_name(rec["account_name"])
                account_name = acc_by_id.get(aid, {}).get("name", "")
                if signal_name and signal_name != normalize_name(account_name):
                    rec["check"] = (f"source names {rec['account_name']}; your account is {account_name} "
                                    "on the same domain: confirm it is the same company")
            if aid is None:
                rec.update(status="unmatched", reason=how)
            elif age > spec["expires_days"]:
                rec.update(status="expired", account_id=aid,
                           reason=f"older than {spec['expires_days']} days")
                per_account.setdefault(aid, {"live": [], "expired": []})["expired"].append(rec)
            else:
                factor = recency_factor(age, cfg["recency"])
                rec.update(status="live", account_id=aid, reason=f"matched by {how}",
                           weight=spec["weight"], recency=factor,
                           value=round(spec["weight"] * factor, 4))
                per_account.setdefault(aid, {"live": [], "expired": []})["live"].append(rec)
        counts[rec["status"]] += 1

    scored = []
    for aid, bucket in per_account.items():
        acc = acc_by_id[aid]
        live = bucket["live"]
        best_by_type = {}
        for s in live:
            best_by_type[s["type"]] = max(best_by_type.get(s["type"], 0), s["value"])
        total = round(sum(best_by_type.values()), 2)
        rank = lambda s: (-s["value"], -parse_date(s["event_date"]).toordinal(), s["signal_id"])
        citable = sorted((s for s in live if s["weight"] > 0 and s["type"] not in cfg["timing_only"]), key=rank)
        timing = sorted((s for s in live if s["weight"] > 0 and s["type"] in cfg["timing_only"]), key=rank)

        why_not = []
        status = (acc.get("status") or "").strip().lower()
        rel = (acc.get("relationship") or "").strip().lower()
        if status in cfg["blocked_status"]:
            why_not.append(f"account status is {status}")
        if rel in cfg["blocked_relationships"]:
            why_not.append(f"relationship is {rel}")
        fit_verdict, fit_reason = icp_fit(acc, cfg["icp"])
        if fit_verdict == "out" and not fit_reason.startswith("excluded relationship"):
            why_not.append(f"outside the ICP: {fit_reason}")
        elif fit_verdict == "unknown":
            why_not.append(f"fit unknown: {fit_reason}")
        if not live:
            why_not.append("no live signals (all expired)")
        elif not citable and not timing:
            why_not.append("only context signals (weight 0)")
        elif not citable:
            why_not.append("intent only: find a citable reason first")
        playable = not why_not
        quadrant = QUADRANTS[(fit_verdict == "in", bool(citable))]

        lead = citable[0] if citable else (timing[0] if timing else None)
        if lead is None:
            strongest = max(cfg["types"].items(), key=lambda kv: (kv[1]["weight"], kv[0]))
            why_now = ("weak case: nothing dated to point to. Watch for "
                       f"{strongest[1].get('watch', strongest[0])}.")
            row = {"top_type": "", "source_url": "", "event_date": "", "seat": "", "check": ""}
        elif lead["type"] in cfg["timing_only"]:
            why_now = (f"Timing only: research interest seen {lead['event_date']}. Use as timing only, "
                       "do not mention it. Find a citable reason before the first touch.")
            row = {"top_type": lead["type"], "source_url": "", "event_date": lead["event_date"],
                   "seat": cfg["types"][lead["type"]].get("seat", ""), "check": lead["check"]}
        else:
            why_now = why_now_sentence(lead)
            seat = cfg["types"][lead["type"]].get("seat", "")
            person = ", ".join(x for x in (lead["person_name"], lead["person_title"]) if x)
            if lead["type"] == "new_leader" and person:
                seat = f"{person} (the named new leader)"
            elif lead["type"] == "leader_gap" and lead["person_name"]:
                seat = f"{seat}; not {lead['person_name']}"
            row = {"top_type": lead["type"], "source_url": lead["source_url"],
                   "event_date": lead["event_date"], "seat": seat, "check": lead["check"]}
        row.update(account_id=aid, name=acc.get("name", ""), score=total,
                   playable="yes" if playable else "no", why_not="; ".join(why_not), why_now=why_now,
                   quadrant=quadrant,
                   live_signals=len(live),
                   signals="; ".join(f"{s['type']}:{s['event_date']}" for s in sorted(live, key=rank)))
        scored.append(row)

    scored.sort(key=lambda r: (r["playable"] != "yes", -r["score"], r["account_id"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("scored.csv", "signals.csv", "report.md"):
        target = (out_dir / name).resolve()
        if target == accounts_path.resolve() or target == config_path.resolve():
            raise ValueError(f"refusing to overwrite an input file: {target}")
    write_csv(out_dir / "scored.csv", SCORED_COLUMNS, scored)
    write_csv(out_dir / "signals.csv", TRACE_COLUMNS, trace)
    (out_dir / "report.md").write_text(render_report(today, files, workspace, skipped_folders,
                                                      counts, scored, trace), encoding="utf-8")
    return {"counts": counts, "scored": scored, "trace": trace, "files": [str(f) for f in files],
            "skipped_folders": skipped_folders, "out": str(out_dir)}


# Fit by timing: fit is the gate, a citable live signal is the timing. Status is separate.
QUADRANTS = {(True, True): "act", (True, False): "nurture", (False, True): "verify", (False, False): "suppress"}
QUADRANT_ACTIONS = [
    ("act", "fits and has a citable reason now: work it if the gate allows"),
    ("nurture", "fits but nothing citable yet: watch for a signal"),
    ("verify", "a fresh signal but the fit is out or unknown: check the fit before any touch"),
    ("suppress", "out or unknown fit and nothing citable: leave it"),
]


def render_report(today, files, workspace, skipped_folders, counts, scored, trace):
    playable = [r for r in scored if r["playable"] == "yes"]
    held = [r for r in scored if r["playable"] != "yes"]
    lines = [f"# Signal scores, {today.isoformat()}", "",
             "Read only. Nothing was sent and no system was changed.", "",
             "## Inputs",
             f"- Raw files read: {len(files)} ({', '.join(f.relative_to(workspace).as_posix() for f in files) or 'none'})"]
    if skipped_folders:
        lines.append(f"- Folders ignored (not a date, or after today): {', '.join(skipped_folders)}")
    lines += [f"- Rows: {counts['read']} read, {counts['live']} live, {counts['expired']} expired, "
              f"{counts['unmatched']} unmatched, {counts['skipped']} skipped, {counts['duplicate']} duplicate", "",
              f"## Playable accounts ({len(playable)})", ""]
    if playable:
        lines += ["| Account | Score | Why now | Seat |", "| --- | --- | --- | --- |"]
        lines += [f"| {r['name']} | {r['score']} | {r['why_now']} | {r['seat']} |" for r in playable]
    else:
        lines.append("None.")
    lines += ["", "## Fit by timing", "", "| Quadrant | Accounts | What to do |", "| --- | --- | --- |"]
    for name, action in QUADRANT_ACTIONS:
        members = [r["name"] for r in scored if r.get("quadrant") == name]
        lines.append(f"| {name} | {', '.join(members) or 'none'} | {action} |")
    lines += ["", f"## Held ({len(held)})", ""]
    lines += [f"- {r['name']}: {r['why_not']}" for r in held] or ["None."]
    checks = [t for t in trace if t.get("check")]
    lines += ["", f"## Check before use ({len(checks)})", ""]
    lines += [f"- {t['signal_id'] or '(no id)'}: {t['check']}" for t in checks] or ["None."]
    problems = [t for t in trace if t["status"] in ("unmatched", "skipped")]
    lines += ["", f"## Not used ({len(problems)})", ""]
    lines += [f"- {t['signal_id'] or '(no id)'} {t['account_name'] or t['domain']}: {t['status']}, {t['reason']}"
              for t in problems] or ["None."]
    lines += ["", "## Before the first touch", "",
              "- Open each source link and check it still says what the why-now line says. "
              "If it is gone or wrong, do not use it.",
              "- Never mention intent or research-interest data in a message.",
              "- Scores are a sort order, not a promise. Weights and windows live in gtm.json.", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default="gtm", help="GTM workspace folder (default: ./gtm)")
    ap.add_argument("--today", required=True, help="scoring date, YYYY-MM-DD")
    ap.add_argument("--accounts", help="accounts CSV (default: <workspace>/input/accounts.csv)")
    ap.add_argument("--config", help="config JSON (default: <workspace>/gtm.json)")
    ap.add_argument("--out", help="output folder (default: <workspace>/signals)")
    args = ap.parse_args(argv)
    today = parse_date(args.today)
    if today is None:
        ap.error("--today must be YYYY-MM-DD")
    try:
        result = score(args.workspace, today, args.accounts, args.out, args.config)
    except (ValueError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    c = result["counts"]
    playable = [r for r in result["scored"] if r["playable"] == "yes"]
    print(f"Read {c['read']} signal rows from {len(result['files'])} file(s): {c['live']} live, "
          f"{c['expired']} expired, {c['unmatched']} unmatched, {c['skipped']} skipped, {c['duplicate']} duplicate.")
    print(f"{len(result['scored'])} accounts scored, {len(playable)} playable.")
    for r in playable[:10]:
        print(f"  {r['score']:>5}  {r['name']}: {r['why_now']}")
    print(f"Wrote scored.csv, signals.csv and report.md to {result['out']}")
    print("Open each source before the first touch. Nothing was sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
