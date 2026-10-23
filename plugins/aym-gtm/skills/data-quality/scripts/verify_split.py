#!/usr/bin/env python3
"""Join a verification file onto a list and split it into safe and held.

It fails closed: no result, an unclear result, a missing score or a score
below the floor means held. A result for one channel never clears another
(an email result never clears a call). Writes only to --out. Never calls a
vendor; the verification file is something you exported yourself.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

DEFAULTS = {
    "stop_statuses": ["hold", "booked", "not_interested", "wrong_person",
                      "left", "do_not_contact", "archived"],
    "dnc_tags": ["opted_out", "dnc_all"],
    "left_tags": ["moved"],
    "channel_block_tags": {"email": ["bounced"], "call": ["dnc_phone", "phone_failed"], "linkedin": []},
    "clean": {"dnc_note_patterns": ["do not contact", "don't contact", "not to contact",
                                    "unsubscribe", "remove me", "stop emailing"]},
    "verify": {
        "min_score_by_channel": {"email": 80, "call": 80, "linkedin": None},
        "ok_verdicts": {"email": ["valid", "verified", "deliverable"],
                        "phone": ["valid", "direct", "mobile", "connected"],
                        "linkedin": ["match", "valid"]},
    },
}
SOURCE_CHANNEL = {"email": "email", "call": "phone", "linkedin": "linkedin"}
ADDED = ["verify_channel", "verify_verdict", "verify_score", "verify_reason"]


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
        rows = [dict(r) for r in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def infer_channel(filename):
    """Read the channel from the list's file name. Unclear means call, the strictest."""
    name = Path(filename).name.lower()
    if "linkedin" in name:
        return "linkedin", "from file name"
    if "email" in name or "mail" in name:
        return "email", "from file name"
    if any(w in name for w in ("call", "dial", "phone")):
        return "call", "from file name"
    return "call", "file name unclear, so the strictest channel (call) was used"


def to_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def decide(person, results, channel, cfg):
    """Return (safe, verdict, score, reason) for one person. Pure function."""
    verify = cfg["verify"]
    status = (person.get("status") or "").strip().lower()
    tags = [t.strip().lower() for t in (person.get("tags") or "").split(";") if t.strip()]
    if status in cfg["stop_statuses"]:
        return False, "", "", f"person status is {status}"
    blocked = [t for t in tags if t in cfg["dnc_tags"] + cfg.get("left_tags", []) + cfg["channel_block_tags"].get(channel, [])]
    if blocked:
        return False, "", "", f"tag {blocked[0]}"
    notes = (person.get("notes") or "").lower()
    phrase = next((p for p in cfg["clean"]["dnc_note_patterns"] if p in notes), "")
    if phrase:
        return False, "", "", f"notes say '{phrase}': record it as do_not_contact"
    need = SOURCE_CHANNEL[channel]
    mine = [r for r in results if (r.get("channel") or "").strip().lower() == need]
    if not mine:
        others = sorted({(r.get("channel") or "").strip().lower() for r in results} - {""})
        if others:
            return False, "", "", (f"only {', '.join(others)} verification; "
                                   f"that never clears a {channel} touch")
        return False, "", "", "no verification result (fail closed)"
    ok_words = [v.lower() for v in verify["ok_verdicts"].get(need, [])]
    verdicts = {(r.get("verdict") or "").strip().lower() for r in mine}
    oks = {v in ok_words for v in verdicts}
    if len(oks) > 1:
        return False, "/".join(sorted(verdicts)), "", "conflicting verification results"
    verdict = sorted(verdicts)[0]
    if True not in oks:
        return False, verdict, "", f"verdict is {verdict or 'blank'}"
    if channel == "email":
        email = (person.get("email") or "").strip().lower()
        checked = {(r.get("email") or "").strip().lower() for r in mine} - {""}
        if checked and email not in checked:
            return False, verdict, "", "the result is for a different email address"
    floor = verify["min_score_by_channel"].get(channel)
    scores = [to_float(r.get("score")) for r in mine]
    if floor is not None:
        if any(s is None for s in scores):
            return False, verdict, "", "no score (fail closed)"
        low = min(scores)
        if low < floor:
            return False, verdict, f"{low:g}", f"score {low:g} below {floor:g}"
        return True, verdict, f"{low:g}", "passed"
    shown = min(s for s in scores if s is not None) if any(s is not None for s in scores) else None
    return True, verdict, "" if shown is None else f"{shown:g}", "passed"


def run(cfg, people, results, channel):
    by_id, by_email = {}, {}
    for r in results:
        pid = (r.get("person_id") or "").strip()
        email = (r.get("email") or "").strip().lower()
        if pid:
            by_id.setdefault(pid, []).append(r)
        elif email:
            by_email.setdefault(email, []).append(r)
    safe, held = [], []
    for person in people:
        pid = (person.get("person_id") or "").strip()
        email = (person.get("email") or "").strip().lower()
        found = list(by_id.get(pid, [])) if pid else []
        if email:
            found += by_email.get(email, [])
        ok, verdict, score, reason = decide(person, found, channel, cfg)
        row = dict(person)
        row.update(verify_channel=channel, verify_verdict=verdict, verify_score=score, verify_reason=reason)
        (safe if ok else held).append(row)
    return safe, held


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", required=True, help="people CSV to check")
    parser.add_argument("--verification", required=True,
                        help="CSV: person_id, email, channel (email|phone|linkedin), verdict, score")
    parser.add_argument("--channel", choices=["email", "call", "linkedin"],
                        help="default: read from the list's file name, else call")
    parser.add_argument("--config", help="gtm.json (optional)")
    parser.add_argument("--out", help="default: <list folder>/verified-<channel>")
    args = parser.parse_args(argv)
    if args.channel:
        channel, how = args.channel, "given"
    else:
        channel, how = infer_channel(args.list)
    out_dir = Path(args.out or Path(args.list).parent / f"verified-{channel}")
    inputs = {Path(p).resolve() for p in (args.list, args.verification) if p}
    if (out_dir.resolve() in {p.parent for p in inputs}
            or any((out_dir / n).resolve() in inputs for n in ("safe.csv", "held.csv"))):
        raise SystemExit("refusing to write into the input folder; choose another --out")
    cfg = load_config(args.config)
    header, people = read_csv(args.list)
    _, results = read_csv(args.verification)
    safe, held = run(cfg, people, results, channel)
    out_dir.mkdir(parents=True, exist_ok=True)
    full = header + [c for c in ADDED if c not in header]
    write_csv(out_dir / "safe.csv", full, safe)
    write_csv(out_dir / "held.csv", full, held)
    print(f"channel: {channel} ({how})")
    print(f"safe: {len(safe)}  held: {len(held)}  -> {out_dir}")
    reasons = {}
    for row in held:
        reasons[row["verify_reason"]] = reasons.get(row["verify_reason"], 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  held {count}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
