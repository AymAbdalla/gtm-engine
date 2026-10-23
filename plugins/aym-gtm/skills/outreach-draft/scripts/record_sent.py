#!/usr/bin/env python3
"""Record drafts the user ticked as sent into log/activity.csv.

The user sends every message by hand and changes `- [ ] sent` to `- [x] sent`.
This script turns each ticked draft into one `sent` row in the activity log so
daily-plan, crm-sync and funnel-review know it happened. It never sends
anything. It only appends to log/activity.csv, and running it twice adds
nothing new: each row's activity_id comes from the drafts file and draft id.

The send time is not in the drafts file. The row uses --sent-at when given,
otherwise noon on --today in the user's time zone, and says the time is
approximate in its notes.
"""

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lint_copy import parse_drafts  # noqa: E402  (same folder)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8
    ZoneInfo = None

LOG_COLUMNS = ["activity_id", "timestamp", "person_id", "account_id", "channel", "direction",
               "sequence", "step", "play_id", "angle", "opener", "outcome", "notes", "source"]
CHANNELS = {"email", "linkedin", "call"}


def read_log(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def default_timestamp(today, workspace, utc_offset):
    """Noon on `today` with the user's UTC offset."""
    if utc_offset:
        sign = 1 if utc_offset[0] == "+" else -1
        hours, minutes = utc_offset[1:].split(":")
        offset = dt.timedelta(hours=int(hours), minutes=int(minutes)) * sign
        return dt.datetime.combine(today, dt.time(12), dt.timezone(offset)).isoformat()
    cfg_path = Path(workspace) / "gtm.json"
    tz = None
    if cfg_path.exists():
        tz = (json.loads(cfg_path.read_text(encoding="utf-8-sig")).get("daily") or {}).get("user_timezone")
    if tz and ZoneInfo is not None:
        return dt.datetime.combine(today, dt.time(12), ZoneInfo(tz)).isoformat()
    raise ValueError("cannot work out your UTC offset: pass --utc-offset=-04:00, or --sent-at")


def plan_rows(drafts, drafts_path, log_rows, timestamp, approximate):
    """Return (new rows, notes). Nothing is written here."""
    seen = {r.get("activity_id") for r in log_rows}
    rows, notes = [], []
    for d in drafts:
        if not d.get("sent"):
            continue
        f = d["fields"]
        activity_id = f"draft-{drafts_path.stem}-{d['id']}"
        if activity_id in seen:
            notes.append(f"{d['id']}: already in the log")
            continue
        person = f.get("person_id", "").strip()
        channel = f.get("channel", "").strip().lower()
        if not person or channel not in CHANNELS:
            notes.append(f"{d['id']}: ticked but missing person_id or a known channel, not recorded")
            continue
        note = f"recorded from {drafts_path.name} {d['id']}"
        if approximate:
            note += "; send time approximate"
        if (f.get("status") or "").strip() == "needs_human":
            note += "; draft was marked needs_human"
        rows.append({"activity_id": activity_id, "timestamp": timestamp, "person_id": person,
                     "account_id": f.get("account_id", ""), "channel": channel, "direction": "out",
                     "sequence": f.get("sequence", ""), "step": f.get("step", ""),
                     "play_id": f.get("play_id", ""), "angle": f.get("angle", ""), "opener": "",
                     "outcome": "sent", "notes": note, "source": "manual"})
        seen.add(activity_id)
    return rows, notes


def append_rows(log_path, rows):
    exists = log_path.exists() and log_path.stat().st_size > 0
    if exists:
        with log_path.open(newline="", encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh), [])
        missing = [c for c in LOG_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"{log_path} is missing columns: {', '.join(missing)}")
    else:
        header = LOG_COLUMNS
        log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore", lineterminator="\n")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Record ticked drafts as sent rows in log/activity.csv.")
    ap.add_argument("--workspace", default="gtm")
    ap.add_argument("--drafts", required=True, help="drafts file, e.g. <workspace>/outreach/drafts/2026-11-02.md")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    ap.add_argument("--sent-at", help="exact send time, ISO 8601 with offset; applies to every ticked draft")
    ap.add_argument("--utc-offset", help="your UTC offset, written as --utc-offset=-04:00, when gtm.json has no daily.user_timezone")
    ap.add_argument("--dry-run", action="store_true", help="show what would be recorded, write nothing")
    args = ap.parse_args(argv)
    try:
        today = dt.date.fromisoformat(args.today)
    except ValueError:
        ap.error("--today must be YYYY-MM-DD")
    drafts_path = Path(args.drafts)
    log_path = Path(args.workspace) / "log" / "activity.csv"
    try:
        if args.sent_at:
            stamp = dt.datetime.fromisoformat(args.sent_at)
            if stamp.utcoffset() is None:
                raise ValueError("--sent-at needs a UTC offset, like 2026-11-02T10:05:00-05:00")
            timestamp, approximate = stamp.isoformat(), False
        else:
            timestamp, approximate = default_timestamp(today, args.workspace, args.utc_offset), True
        drafts = parse_drafts(drafts_path.read_text(encoding="utf-8-sig"))
        rows, notes = plan_rows(drafts, drafts_path, read_log(log_path), timestamp, approximate)
        if rows and not args.dry_run:
            append_rows(log_path, rows)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    verb = "Would record" if args.dry_run else "Recorded"
    print(f"{verb} {len(rows)} sent draft(s) in {log_path}.")
    for r in rows:
        print(f"  {r['activity_id']}: {r['person_id']} {r['channel']} ({r['timestamp']})")
    for n in notes:
        print(f"  note: {n}")
    print("Nothing was sent. This only records what you already sent by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
