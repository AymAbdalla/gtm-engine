#!/usr/bin/env python3
"""Keep a sticky top-N list of accounts.

The first run scores every eligible account and freezes the top N in
book/top.json. Later runs never reshuffle the list. They apply the user's
add/remove overrides and report challengers: accounts outside the list that now
score above the lowest account on it. Use --reset only to start a new list on
purpose. Writes book/top.json and book/top-report.md. No network.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtm_fit import fit_points  # noqa: E402  (shared ICP-fit rule, copied in four skills)

DEFAULT_RANKING = {
    "top_n": 10,
    "tier_points": {"P1": 3, "P2": 2, "P3": 1},
    "readiness_points": {"ready": 3, "enrich": 1, "prospect": 0},
    "per_send_ready_person": 1,
    "send_ready_cap": 3,
    "per_lane_covered": 1,
    "bonus_lanes": {"tech": 1},
    "signal_points": 2,
    "never_rank_strategies": ["hold", "excluded", "live"],
    # Fit is value, staffing is effort: a great fit should beat a well-staffed poor fit.
    "fit_points": {"sweet_spot": 5, "in_band": 0, "segment_match": 2},
}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in csv.DictReader(f)]


def load_ranking(workspace):
    path = workspace / "gtm.json"
    cfg = json.loads(path.read_text()) if path.exists() else {}
    rank = dict(DEFAULT_RANKING)
    rank.update(cfg.get("ranking", {}))
    rank["fit_points"] = dict(DEFAULT_RANKING["fit_points"], **cfg.get("ranking", {}).get("fit_points", {}))
    rank["_cfg"] = cfg
    # Never rank an account the ICP excludes (icp.exclude_relationships), one the
    # user excludes in ranking.never_rank_relationships, or one where a parent decides.
    excluded = cfg.get("icp", {}).get("exclude_relationships", ["competitor", "customer", "partner"])
    own = cfg.get("ranking", {}).get("never_rank_relationships", [])
    rank["never_rank_relationships"] = sorted(set(excluded) | set(own) | {"parent_decides"})
    # Live deals belong to the deal owner, so they never join the outbound list.
    rank["never_rank_strategies"] = sorted(set(rank["never_rank_strategies"]) | {"live"})
    return rank


def points(acct, rank, playable):
    """Additive points with a one-line reason for each part."""
    total, why = 0, []
    tier = rank["tier_points"].get(acct.get("tier", ""), 0)
    if tier:
        total += tier
        why.append(f"tier {acct['tier']} +{tier}")
    ready = rank["readiness_points"].get(acct.get("readiness", ""), 0)
    if ready:
        total += ready
        why.append(f"{acct['readiness']} +{ready}")
    n_ok = min(int(acct.get("send_ok_count") or 0), int(rank["send_ready_cap"]))
    if n_ok:
        total += n_ok * rank["per_send_ready_person"]
        why.append(f"{n_ok} send-ready +{n_ok * rank['per_send_ready_person']}")
    lanes = [l for l in (acct.get("lanes_covered") or "").split(";") if l]
    if lanes:
        total += len(lanes) * rank["per_lane_covered"]
        why.append(f"{len(lanes)} lanes +{len(lanes) * rank['per_lane_covered']}")
    for lane, bonus in rank["bonus_lanes"].items():
        if lane in lanes:
            total += bonus
            why.append(f"{lane} contact +{bonus}")
    fit, detail = fit_points(acct, rank.get("_cfg", {}), rank["fit_points"])
    if fit:
        total += fit
        why.append(f"ICP fit +{fit:g} ({detail})")
    if acct["account_id"] in playable:
        total += rank["signal_points"]
        why.append(f"playable signal +{rank['signal_points']}")
    return total, "; ".join(why) or "no points"


def eligible(acct, rank):
    if acct.get("relationship") in rank["never_rank_relationships"]:
        return False
    if acct.get("strategy") in rank["never_rank_strategies"]:
        return False
    return True


def rank_accounts(workspace, today, reset=False, signals_path=None):
    workspace = Path(workspace)
    book = workspace / "book"
    accounts = read_csv(book / "accounts.csv")
    if not accounts:
        raise ValueError(f"no accounts found in {book / 'accounts.csv'}; run build_book.py first")
    rank = load_ranking(workspace)
    sig_rows = read_csv(Path(signals_path) if signals_path else workspace / "signals" / "scored.csv")
    playable = {r.get("account_id") for r in sig_rows if r.get("playable", "").lower() in ("yes", "true", "1")}

    scored = {}
    for a in accounts:
        if eligible(a, rank):
            pts, why = points(a, rank, playable)
            scored[a["account_id"]] = {"account_id": a["account_id"], "name": a.get("name", ""),
                                       "points": pts, "why": why}
    order = sorted(scored.values(), key=lambda r: (-r["points"], r["account_id"]))

    top_path = book / "top.json"
    if top_path.exists() and not reset:
        top = json.loads(top_path.read_text())
        frozen = True
    else:
        top = {"created": today, "top_n": rank["top_n"],
               "accounts": [r["account_id"] for r in order[: int(rank["top_n"])]],
               "overrides": {"add": [], "remove": []}}
        frozen = False
    overrides = top.setdefault("overrides", {"add": [], "remove": []})
    effective = [a for a in top["accounts"] if a not in overrides.get("remove", [])]
    effective += [a for a in overrides.get("add", []) if a not in effective]
    dropped = [a for a in effective if a not in scored]  # now ineligible: report, never auto-remove
    floor = min((scored[a]["points"] for a in effective if a in scored), default=0)
    challengers = [r for r in order if r["account_id"] not in effective and r["points"] > floor]
    top["effective"] = effective
    top["updated"] = today
    book.mkdir(parents=True, exist_ok=True)
    top_path.write_text(json.dumps(top, indent=2) + "\n", encoding="utf-8")

    lines = [f"# Top accounts ({today})", "",
             "The list is frozen. Edit `overrides.add` / `overrides.remove` in top.json to change it,",
             "or rerun with --reset to start a new list on purpose.", "",
             "| # | Account | Points | Why |", "|---|---|---|---|"]
    for i, aid in enumerate(effective, 1):
        r = scored.get(aid, {"name": aid, "points": "-", "why": "no longer eligible"})
        lines.append(f"| {i} | {r['name']} | {r['points']} | {r['why']} |")
    lines += ["", "## Challengers", ""]
    if challengers:
        lines += [f"- {r['name']} ({r['points']} points, above the list floor of {floor}): {r['why']}"
                  for r in challengers]
    else:
        lines.append("- none")
    if dropped:
        lines += ["", "## On the list but no longer eligible", ""]
        lines += [f"- {a}: check its strategy or relationship, then remove it by override" for a in dropped]
    (book / "top-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"frozen": frozen, "effective": effective, "challengers": [r["account_id"] for r in challengers],
            "ineligible_on_list": dropped}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default="gtm")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    ap.add_argument("--reset", action="store_true", help="start a new list on purpose")
    ap.add_argument("--signals", help="scored signals CSV (default: <workspace>/signals/scored.csv)")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.today):
        ap.error("--today must be YYYY-MM-DD")
    try:
        res = rank_accounts(args.workspace, args.today, args.reset, args.signals)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    state = "kept the frozen list" if res["frozen"] else "created a new list"
    print(f"Top accounts: {state} of {len(res['effective'])}")
    print(f"  challengers: {', '.join(res['challengers']) or 'none'}")
    if res["ineligible_on_list"]:
        print(f"  no longer eligible but still listed: {', '.join(res['ineligible_on_list'])}")
    print("  report: book/top-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
