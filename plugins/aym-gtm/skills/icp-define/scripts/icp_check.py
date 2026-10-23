#!/usr/bin/env python3
"""Check a gtm.json config and sort an accounts list against the ICP.

What it does:
  1. Validates gtm.json: required sections, ordered size bands, regexes that
     compile, counts that name a source. Errors stop the run; warnings do not.
  2. If an accounts CSV is given (or found at <workspace>/input/accounts.csv),
     marks every account in, out or unknown with one plain reason, its size
     band, its segment and its account points.
  3. Prints a market size estimate per segment from counts the user supplied
     in gtm.json, with the noise check applied and a band label. These are
     estimates, not forecasts.

It reads files only. It writes only when --out is given, and never over an
input file. Standard library only, no network.
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

ALLOWED_RELATIONSHIPS = {"competitor", "customer", "partner", "parent_decides"}
ALLOWED_ROLES = {"decision_maker", "champion", "influencer", "technical_gatekeeper", "user"}
ALLOWED_EMAIL_STATUS = {"verified", "risky", "catch_all", "invalid", "unknown"}
ALLOWED_PERSON_STATUS = {"active", "nurture", "hold", "booked", "not_interested", "wrong_person",
                         "left", "do_not_contact", "archived"}
DEFAULT_BANDS = [
    {"label": "too narrow", "max": 249},
    {"label": "tight", "max": 999},
    {"label": "sweet spot", "max": 4999},
    {"label": "healthy", "max": 50000},
    {"label": "too broad", "max": None},
]
DEFAULT_ACCOUNT_POINTS = {"sweet_spot": 3, "in_band": 1, "segment_match": 1, "tier": {}}
EXTRA_COLUMNS = ["in_icp", "icp_reason", "size_band", "segment", "account_points", "points_detail"]


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_patterns(patterns, where, errors):
    if not isinstance(patterns, list):
        errors.append(f"{where} must be a list of patterns")
        return
    for pat in patterns:
        try:
            re.compile(str(pat), re.I)
        except re.error as exc:
            errors.append(f"{where}: pattern {pat!r} does not compile ({exc})")


def validate_config(cfg):
    """Return (errors, warnings). Errors mean other skills cannot trust the file."""
    errors, warnings = [], []
    if not isinstance(cfg, dict):
        return ["gtm.json must be a JSON object"], warnings

    icp = cfg.get("icp")
    if not isinstance(icp, dict):
        errors.append("missing section: icp")
        icp = {}
    size = icp.get("size", {})
    keys = ("min", "sweet_min", "sweet_max", "max")
    if not all(_num(size.get(k)) for k in keys):
        errors.append("icp.size needs numbers for min, sweet_min, sweet_max and max")
    elif not (0 <= size["min"] <= size["sweet_min"] <= size["sweet_max"] <= size["max"]):
        errors.append("icp.size must be ordered: 0 <= min <= sweet_min <= sweet_max <= max")
    countries = icp.get("countries")
    if not countries or not isinstance(countries, list):
        errors.append("icp.countries must be a non-empty list")
    ind_in = [str(i).lower() for i in icp.get("industries_in", [])]
    ind_out = [str(i).lower() for i in icp.get("industries_out", [])]
    both = sorted(set(ind_in) & set(ind_out))
    if both:
        errors.append(f"industries listed as both in and out: {', '.join(both)}")
    if not ind_in:
        warnings.append("icp.industries_in is empty: every industry not listed as out will count as in")
    for rel in icp.get("exclude_relationships", []):
        if rel not in ALLOWED_RELATIONSHIPS:
            warnings.append(f"unknown relationship {rel!r} in exclude_relationships")

    personas = cfg.get("personas")
    if not isinstance(personas, list) or not personas:
        errors.append("missing section: personas (at least one)")
        personas = []
    seen = set()
    for i, p in enumerate(personas):
        pid = p.get("id") if isinstance(p, dict) else None
        if not pid:
            errors.append(f"persona #{i + 1} has no id")
            continue
        if pid in seen:
            errors.append(f"persona id {pid!r} is used twice")
        seen.add(pid)
        if not p.get("lane"):
            errors.append(f"persona {pid}: lane is missing")
        if p.get("role") not in ALLOWED_ROLES:
            errors.append(f"persona {pid}: role must be one of {', '.join(sorted(ALLOWED_ROLES))}")
        if not p.get("title_patterns"):
            errors.append(f"persona {pid}: title_patterns is empty")
        _check_patterns(p.get("title_patterns", []), f"persona {pid}", errors)
        if not _num(p.get("points", 0)):
            errors.append(f"persona {pid}: points must be a number")
    _check_patterns(cfg.get("not_buyer_titles", []), "not_buyer_titles", errors)
    _check_patterns(cfg.get("review_titles", []), "review_titles", errors)
    rule = cfg.get("region_title_rule")
    if isinstance(rule, dict):
        _check_patterns(rule.get("other_region_words", []), "region_title_rule.other_region_words", errors)
        _check_patterns(rule.get("senior_exempt_patterns", []), "region_title_rule.senior_exempt_patterns", errors)

    seg_ids = set()
    for i, seg in enumerate(cfg.get("segments", [])):
        sid = seg.get("id")
        if not sid:
            errors.append(f"segment #{i + 1} has no id")
            continue
        if sid in seg_ids:
            errors.append(f"segment id {sid!r} is used twice")
        seg_ids.add(sid)
        for ind in seg.get("industries", []):
            if ind_in and str(ind).lower() not in ind_in:
                warnings.append(f"segment {sid}: industry {ind!r} is not in icp.industries_in")
        smin, smax = seg.get("size_min"), seg.get("size_max")
        if _num(smin) and _num(smax) and smin > smax:
            errors.append(f"segment {sid}: size_min is above size_max")
        if _num(smin) and _num(size.get("min")) and smin < size["min"]:
            warnings.append(f"segment {sid}: size_min is below the ICP floor")
        if _num(smax) and _num(size.get("max")) and smax > size["max"]:
            warnings.append(f"segment {sid}: size_max is above the ICP ceiling")
        if "market_count" in seg:
            if not (isinstance(seg["market_count"], int) and seg["market_count"] >= 0):
                errors.append(f"segment {sid}: market_count must be a whole number, 0 or more")
            if not str(seg.get("market_count_source", "")).strip():
                errors.append(f"segment {sid}: market_count has no market_count_source, so it cannot be used")
        noise = seg.get("noise_check")
        if noise is not None:
            reviewed, noisy = noise.get("reviewed"), noise.get("noisy")
            if not (isinstance(reviewed, int) and reviewed > 0 and isinstance(noisy, int) and 0 <= noisy <= reviewed):
                errors.append(f"segment {sid}: noise_check needs reviewed > 0 and 0 <= noisy <= reviewed")
    if not cfg.get("segments"):
        warnings.append("no segments yet: accounts will be in or out of the ICP but not grouped")

    bands = cfg.get("market_bands", DEFAULT_BANDS)
    maxes = [b.get("max") for b in bands]
    if not bands or maxes[-1] is not None or any(m is None for m in maxes[:-1]):
        errors.append("market_bands: every band needs a max except the last, which must be null")
    elif any(a >= b for a, b in zip(maxes[:-2], maxes[1:-1])):
        errors.append("market_bands: max values must go up")

    gate = cfg.get("send_gate")
    if isinstance(gate, dict):
        bad = set(gate.get("email_status_ok", [])) - ALLOWED_EMAIL_STATUS
        if bad:
            errors.append(f"send_gate.email_status_ok has unknown values: {', '.join(sorted(bad))}")
        score = gate.get("min_email_score")
        if score is not None and not (_num(score) and 0 <= score <= 100):
            errors.append("send_gate.min_email_score must be 0 to 100 or null")
        for old_key in ("block_person_status", "block_tags"):
            if old_key in gate:
                errors.append(f"send_gate.{old_key} moved: use top-level stop_statuses and dnc_tags")
    else:
        warnings.append("section send_gate missing: skills will use their defaults")

    bad = set(cfg.get("stop_statuses", [])) - ALLOWED_PERSON_STATUS
    if bad:
        errors.append(f"stop_statuses has unknown values: {', '.join(sorted(bad))}")
    if "do_not_contact" not in cfg.get("stop_statuses", ["do_not_contact"]):
        errors.append("stop_statuses must include do_not_contact")
    for key in ("dnc_tags", "left_tags"):
        if not isinstance(cfg.get(key, []), list):
            errors.append(f"{key} must be a list")
    both = set(cfg.get("dnc_tags", []) or []) & set(cfg.get("left_tags", []) or [])
    if both:
        errors.append(f"a tag cannot be both an opt-out and a left tag: {', '.join(sorted(both))}")
    cbt = cfg.get("channel_block_tags", {})
    if not isinstance(cbt, dict) or any(not isinstance(v, list) for v in cbt.values()):
        errors.append("channel_block_tags must map a channel (email, call, linkedin) to a list of tags")
    elif set(cbt) - {"email", "call", "linkedin"}:
        errors.append("channel_block_tags: channels are email, call and linkedin")
    if not isinstance(cfg.get("freemail_domains", []), list):
        errors.append("freemail_domains must be a list")

    sig = cfg.get("signals")
    if isinstance(sig, dict):
        for name, t in sig.get("types", {}).items():
            if not (_num(t.get("weight")) and t["weight"] >= 0):
                errors.append(f"signals.types.{name}: weight must be a number, 0 or more")
            if not (isinstance(t.get("expires_days"), int) and t["expires_days"] > 0):
                errors.append(f"signals.types.{name}: expires_days must be a whole number above 0")
        steps = sig.get("recency", [])
        days = [s[0] for s in steps if isinstance(s, list) and len(s) == 2]
        if len(days) != len(steps) or days != sorted(days) or len(set(days)) != len(days):
            errors.append("signals.recency must be [days, factor] pairs with days going up")
        elif any(not (_num(s[1]) and 0 <= s[1] <= 1) for s in steps):
            errors.append("signals.recency factors must be between 0 and 1")
    else:
        warnings.append("section signals missing: signal-score will use its defaults")

    copy = cfg.get("copy")
    if isinstance(copy, dict):
        lo, hi, hard = copy.get("min_words"), copy.get("max_words"), copy.get("hard_max_words")
        if all(_num(x) for x in (lo, hi, hard)) and not (lo <= hi <= hard):
            errors.append("copy: min_words <= max_words <= hard_max_words is required")
    else:
        warnings.append("section copy missing: outreach-draft will use its defaults")
    return errors, warnings


def _employees(value):
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (ValueError, OverflowError):  # "nan" and "inf" are not headcounts
        return None


def size_band(n, size):
    if n is None:
        return "unknown"
    if size["sweet_min"] <= n <= size["sweet_max"]:
        return "sweet_spot"
    if size["min"] <= n <= size["max"]:
        return "in_band"
    return "below" if n < size["min"] else "above"


def classify_account(row, cfg):
    """Return the extra columns for one account. Fit only: status does not change fit."""
    icp = cfg["icp"]
    size = icp["size"]
    industry = (row.get("industry") or "").strip().lower()
    n = _employees(row.get("employees"))
    band = size_band(n, size)
    out = {"in_icp": "no", "icp_reason": "", "size_band": band, "segment": "", "account_points": 0,
           "points_detail": ""}

    verdict, reason = icp_fit(row, icp)
    out["in_icp"] = {"in": "yes", "out": "no", "unknown": "unknown"}[verdict]
    out["icp_reason"] = reason

    if out["in_icp"] == "yes":
        for seg in cfg.get("segments", []):
            inds = [str(i).lower() for i in seg.get("industries", [])]
            lo = seg.get("size_min", size["min"])
            hi = seg.get("size_max", size["max"])
            if (not inds or industry in inds) and lo <= n <= hi:
                out["segment"] = seg["id"]
                break
        else:
            out["segment"] = "unsegmented"
        pts = dict(DEFAULT_ACCOUNT_POINTS)
        pts.update(cfg.get("scoring", {}).get("account", {}))
        # Show each part of the score so a person can check and adjust the weights.
        tier = (row.get("tier") or "").strip()
        parts = [(band, pts.get(band, 0))]
        if out["segment"] != "unsegmented":
            parts.append(("segment_match", pts.get("segment_match", 0)))
        if tier:
            parts.append(("tier " + tier, pts.get("tier", {}).get(tier, 0)))
        out["account_points"] = sum(v for _, v in parts)
        out["points_detail"] = "; ".join(f"{name} {value}" for name, value in parts)
    return out


def two_sig(n):
    if n == 0:
        return 0
    return int(round(n, -int(math.floor(math.log10(abs(n)))) + 1))


def band_label(n, bands):
    for b in bands:
        if b["max"] is None or n <= b["max"]:
            return b["label"]
    return bands[-1]["label"]


def market_estimates(cfg, counts_in_list):
    """One row per segment. Uses only counts the user supplied with a source."""
    bands = cfg.get("market_bands", DEFAULT_BANDS)
    acv = cfg.get("seller", {}).get("average_contract_value")
    rows = []
    for seg in cfg.get("segments", []):
        sid = seg["id"]
        row = {"segment": sid, "label": seg.get("label", sid), "in_list": counts_in_list.get(sid, 0),
               "estimate": None, "band": "", "source": "", "note": "", "sam": None}
        if "market_count" not in seg:
            row["note"] = "no count source yet; only your list is counted"
            rows.append(row)
            continue
        count = seg["market_count"]
        noise = seg.get("noise_check")
        if noise:
            count = count * (1 - noise["noisy"] / noise["reviewed"])
            row["note"] = f"noise check: {noise['noisy']} of {noise['reviewed']} sample rows did not fit"
        else:
            row["note"] = "no noise check yet: review 25 sample rows and record how many do not fit"
        row["estimate"] = two_sig(count)
        row["band"] = band_label(count, bands)
        row["source"] = seg.get("market_count_source", "")
        share = seg.get("addressable_share")
        if _num(acv) and _num(share):
            row["sam"] = two_sig(count * share * acv)
        rows.append(row)
    return rows


def read_accounts(path, required=("account_id", "industry", "country", "employees")):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    missing = [c for c in required if c not in fields]
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(missing)}")
    rows.sort(key=lambda r: r.get("account_id", ""))
    return fields, rows


def render_report(results, estimates, errors, warnings, accounts_path, won=None):
    lines = ["# ICP check", ""]
    if won is not None:
        lines += ["## Won deals against the ICP", "",
                  f"{won['inside']} of {won['total']} won deals inside the ICP. A low share means the ICP "
                  "does not describe who actually buys: revisit it before scaling outbound.", ""]
        if won["outside"]:
            lines += ["| won deal | why outside |", "|---|---|"]
            lines += [f"| {name} | {reason} |" for name, reason in won["outside"]]
            lines.append("")
        if won.get("unknown"):
            lines += [f"{len(won['unknown'])} unknown: the fit rule cannot judge them yet.", "",
                      "| won deal | why unknown |", "|---|---|"]
            lines += [f"| {name} | {reason} |" for name, reason in won["unknown"]]
            lines.append("")
    if errors:
        lines += ["## Config errors (fix these first)", ""] + [f"- {e}" for e in errors] + [""]
    if warnings:
        lines += ["## Config warnings", ""] + [f"- {w}" for w in warnings] + [""]
    if results is not None:
        yes = sum(1 for _, r in results if r["in_icp"] == "yes")
        no = sum(1 for _, r in results if r["in_icp"] == "no")
        unk = sum(1 for _, r in results if r["in_icp"] == "unknown")
        lines += ["## Accounts in your list", "", f"Source: `{accounts_path}`", "",
                  f"- In the ICP: {yes}", f"- Out of the ICP: {no}", f"- Unknown (enrich first): {unk}", "",
                  "| account_id | name | in ICP | reason | size band | segment | points |",
                  "|---|---|---|---|---|---|---|"]
        for row, r in results:
            lines.append(f"| {row.get('account_id', '')} | {row.get('name', '')} | {r['in_icp']} | {r['icp_reason']} | "
                         f"{r['size_band']} | {r['segment']} | {r['account_points']} |")
        lines.append("")
    if estimates:
        lines += ["## Market size by segment (estimate, not forecast)", "",
                  "| segment | in your list | estimate | band | source | note |", "|---|---|---|---|---|---|"]
        for e in estimates:
            est = "" if e["estimate"] is None else f"{e['estimate']:,}"
            lines.append(f"| {e['segment']} | {e['in_list']} | {est} | {e['band']} | {e['source']} | {e['note']} |")
        sams = [e for e in estimates if e["sam"] is not None]
        if sams:
            lines += ["", "Serviceable revenue (hypothesis, not forecast): " +
                      "; ".join(f"{e['segment']} {e['sam']:,}" for e in sams)]
        lines.append("")
    lines.append("Thresholds and bands come from gtm.json. They are editable defaults, not standards.")
    return "\n".join(lines) + "\n"


def won_deals_check(won_rows, account_rows, cfg):
    """How many won deals fall inside the ICP. A won deal is a customer by now, so its
    relationship is ignored. A row with only account_id is looked up in the accounts list.
    A deal the fit rule cannot judge (not in the list, or blank fields) is unknown, not outside."""
    by_id = {r.get("account_id", ""): r for r in account_rows or []}
    inside, outside, unknown, total = 0, [], [], 0
    for w in won_rows:
        row = dict(by_id.get(w.get("account_id", ""), {}))
        row.update({k: v for k, v in w.items() if v})
        row["relationship"] = ""
        total += 1
        verdict, reason = icp_fit(row, cfg["icp"])
        name = row.get("name") or row.get("account_id") or "unnamed"
        if verdict == "in":
            inside += 1
        elif verdict == "out":
            outside.append((name, reason))
        else:
            if w.get("account_id") not in by_id and not any(w.get(k) for k in ("industry", "country", "employees")):
                reason = "not in the accounts list: add its industry, country and employees"
            unknown.append((name, reason))
    return {"total": total, "inside": inside, "outside": outside, "unknown": unknown}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate gtm.json and sort accounts against the ICP.")
    ap.add_argument("--workspace", default="gtm", help="GTM workspace folder (default ./gtm)")
    ap.add_argument("--config", help="path to gtm.json (default <workspace>/gtm.json)")
    ap.add_argument("--accounts", help="accounts CSV (default <workspace>/input/accounts.csv if it exists)")
    ap.add_argument("--out", help="folder to write accounts-icp.csv and icp-check.md")
    ap.add_argument("--won", help="won deals CSV (default <workspace>/input/won-deals.csv if it exists)")
    ap.add_argument("--today", help="YYYY-MM-DD for the review date check (default: today)")
    args = ap.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        ap.error("--today must be YYYY-MM-DD")

    ws = Path(args.workspace)
    cfg_path = Path(args.config) if args.config else ws / "gtm.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read config {cfg_path}: {exc}", file=sys.stderr)
        return 2
    errors, warnings = validate_config(cfg)
    review_by = (cfg.get("icp") or {}).get("review_by")
    if review_by:
        try:
            if date.fromisoformat(str(review_by)) < today:
                warnings.append(f"review the ICP: icp.review_by {review_by} has passed")
        except ValueError:
            errors.append(f"icp.review_by must be YYYY-MM-DD, got {review_by!r}")

    acc_path = Path(args.accounts) if args.accounts else ws / "input" / "accounts.csv"
    results, fields, rows = None, [], []
    if errors:
        print("Config errors:")
        for e in errors:
            print(f"  - {e}")
        print("Fix the config before sorting accounts.")
        return 1
    if args.accounts or acc_path.exists():
        try:
            fields, rows = read_accounts(acc_path)
        except (OSError, ValueError) as exc:
            print(f"Cannot read accounts: {exc}", file=sys.stderr)
            return 2
        results = [(row, classify_account(row, cfg)) for row in rows]

    won_path = Path(args.won) if args.won else ws / "input" / "won-deals.csv"
    won = None
    if args.won or won_path.exists():
        try:
            _, won_rows = read_accounts(won_path, required=("account_id",))
        except (OSError, ValueError) as exc:
            print(f"Cannot read won deals: {exc}", file=sys.stderr)
            return 2
        won = won_deals_check(won_rows, rows, cfg)

    counts = {}
    for _, r in results or []:
        if r["segment"]:
            counts[r["segment"]] = counts.get(r["segment"], 0) + 1
    estimates = market_estimates(cfg, counts)

    print(f"Config OK: {cfg_path}" + (f" ({len(warnings)} warnings)" if warnings else ""))
    for w in warnings:
        print(f"  warning: {w}")
    if results is not None:
        tally = {}
        for _, r in results:
            tally[r["in_icp"]] = tally.get(r["in_icp"], 0) + 1
        print(f"Accounts: {len(results)} read; in {tally.get('yes', 0)}, out {tally.get('no', 0)}, "
              f"unknown {tally.get('unknown', 0)}")
    if won is not None:
        print(f"Won deals: {won['inside']} of {won['total']} won deals inside the ICP"
              + (f"; outside: {', '.join(n for n, _ in won['outside'])}" if won["outside"] else "")
              + (f"; {len(won['unknown'])} unknown: {', '.join(n for n, _ in won['unknown'])}"
                 if won.get("unknown") else ""))
    for e in estimates:
        est = "no count source" if e["estimate"] is None else f"~{e['estimate']:,} ({e['band']})"
        print(f"  segment {e['segment']}: {e['in_list']} in list; market {est}")
    if estimates:
        print("Market numbers are estimates, not forecasts.")

    if args.out:
        out = Path(args.out)
        targets = [out / "accounts-icp.csv", out / "icp-check.md"]
        inputs = {cfg_path.resolve(), acc_path.resolve()}
        if any(t.resolve() in inputs for t in targets):
            print("Refusing to write over an input file.", file=sys.stderr)
            return 2
        out.mkdir(parents=True, exist_ok=True)
        if results is not None:
            with open(targets[0], "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields + [c for c in EXTRA_COLUMNS if c not in fields])
                writer.writeheader()
                for row, r in results:
                    writer.writerow({**row, **r})
        targets[1].write_text(render_report(results, estimates, errors, warnings, acc_path, won), encoding="utf-8")
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
