#!/usr/bin/env python3
"""Turn approved enrollments, sequences and the activity log into today's work file, and close the day.

Plan mode (default):
  python3 plan_day.py --workspace gtm --today 2026-10-20
  Writes plan/<today>.md and plan/<today>.csv. Uses only log rows from before today, so a rerun in the
  afternoon shows the same morning plan. A rerun keeps the skip_reason entries (and any column you added)
  you wrote in plan/<today>.csv, matched by person, sequence, step and channel. An entry whose card is gone
  is listed in the plan and kept in plan/<today>-unmatched.csv until its card returns.

Nudge mode:
  python3 plan_day.py --workspace gtm --today 2026-10-20 --nudge
  Prints one line: what to do first, or a line starting "FAILED:". Writes nothing.

Close mode:
  python3 plan_day.py --workspace gtm --today 2026-10-20 --close
  Reads plan/<today>.csv and today's log rows. Every card ends as done, skipped (you filled skip_reason)
  or "no record". Writes plan/<today>-close.md with commitments and tomorrow's top 3.

Reads files and writes files under plan/ only. Never sends, enrolls, dials or writes to a CRM.
"""
import argparse
import csv
import glob
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8: fixed table with the US and Canada daylight saving rule
    ZoneInfo = None

DEFAULT_DAILY = {
    "user_timezone": "America/New_York",
    "holidays": [],
    "call_window": {"start": "08:00", "end": "21:00"},
    "preferred_window": {"start": "09:00", "end": "17:00"},
    "call_blocks": [
        {"name": "morning", "start": "09:30", "end": "11:30"},
        {"name": "afternoon", "start": "14:00", "end": "16:30"},
    ],
    "call_slot_minutes": 5,
    "min_days_between_touches": 3,
    "max_extra_cards": 20,
    "extras_per_account": 1,
    "inbound_tags": ["inbound"],
    "warm_tags": ["warm", "referral", "past_reply"],
    "weights": {"signal": 3, "seat": 2, "recency": 1, "fit": 2, "due_step": 2,
                "single_threaded": 1, "deliverability": 1},
    "recency_peak_days": [4, 14],
    "never_touched_recency": 0.8,
    "flat_gap": 0.05,
    "fact_ladder": ["inbound_untouched", "never_touched", "buying_role", "seniority", "newest"],
    "block_order": ["inbound", "warm", "linkedin_only", "volume"],
    "reply_lookback_days": 30,
    "owner": None,
}
DEFAULT_SHARED = {
    "stop_statuses": ["hold", "booked", "not_interested", "wrong_person", "left", "do_not_contact", "archived"],
    "dnc_tags": ["opted_out", "dnc_all"],
    "left_tags": ["moved"],
    "channel_block_tags": {"email": ["bounced"], "call": ["dnc_phone", "phone_failed"], "linkedin": []},
    "not_buyer_titles": [r"\bintern\b", "student", "recruit", "sales rep", "account executive"],
}
DEFAULT_EXCLUDE_RELATIONSHIPS = ["competitor", "customer", "partner", "parent_decides"]
DEFAULT_DNC_NOTES = ["do not contact", "don't contact", "not to contact", "unsubscribe", "remove me",
                     "stop emailing"]
NO_OUTBOUND = {"live", "hold", "excluded"}
TEMPLATE_NOTE = "filled from the template; read it before sending"


def quoted_source(enroll_vars, text):
    """The source link to open when a card's text quotes the enrollment's dated fact."""
    if not isinstance(enroll_vars, dict):
        return ""
    fact, url = (enroll_vars.get("trigger_fact") or "").strip(), (enroll_vars.get("source_url") or "").strip()
    return url if fact and url and fact in (text or "") else ""
# Outcomes that end a sequence for the person; the first five also stop everyone at the account.
ACCOUNT_STOP = {"replied", "interested", "not_now", "not_interested", "booked"}
PERSON_STOP = ACCOUNT_STOP | {"opt_out", "wrong_person", "left", "bounced"}
# Outcomes that end every touch for the person whenever they happened, even before a sequence start.
LASTING_STOP = {"opt_out", "not_interested", "wrong_person", "left"}
OUTCOMES = {"sent", "connected", "no_answer", "voicemail", "bad_number", "gatekeeper", "replied", "interested",
            "not_now", "not_interested", "booked", "bounced", "opt_out", "wrong_person", "left"}
ROLE_SCORE = {"decision_maker": 1.0, "champion": 0.8, "influencer": 0.5, "technical_gatekeeper": 0.4}
TIER_SCORE = {"P1": 1.0, "P2": 0.7, "P3": 0.4}
SENIOR = [(r"\b(chief|cfo|ceo|coo|cio|cto)\b", 4), (r"\b(vp|vice president|head of)\b", 3),
          (r"\bdirector\b", 2), (r"\b(manager|lead|controller)\b", 1)]
PLAN_COLS = ["card_id", "date", "order", "kind", "block", "person_id", "account_id", "name", "title", "account",
             "channel", "sequence", "step", "play_id", "status", "slot_start", "prospect_local", "prep",
             "subject", "body", "score", "why", "skip_reason"]
VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

# Python 3.8 fallback: standard offsets in hours and whether the zone uses daylight saving time.
FALLBACK_TZ = {
    "America/New_York": (-5, True), "America/Toronto": (-5, True), "America/Detroit": (-5, True),
    "America/Chicago": (-6, True), "America/Winnipeg": (-6, True), "America/Denver": (-7, True),
    "America/Edmonton": (-7, True), "America/Phoenix": (-7, False), "America/Los_Angeles": (-8, True),
    "America/Vancouver": (-8, True), "America/Anchorage": (-9, True), "America/Halifax": (-4, True),
    "Pacific/Honolulu": (-10, False), "UTC": (0, False),
}


# ---------- small helpers ----------

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def split_list(value):
    return [x.strip() for x in (value or "").replace(",", ";").split(";") if x.strip()]


def deep_merge(base, extra):
    out = json.loads(json.dumps(base))
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_date(s):
    try:
        return datetime.strptime((s or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_hhmm(s):
    h, m = (s or "0:0").split(":")
    return time(int(h), int(m))


def _nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def utc_offset(tz_name, day):
    """UTC offset for a named zone on a date (at local noon). None when the zone is unknown."""
    if ZoneInfo is not None:
        try:
            return datetime.combine(day, time(12), ZoneInfo(tz_name)).utcoffset()
        except Exception:
            return None
    if tz_name not in FALLBACK_TZ:
        return None
    hours, dst = FALLBACK_TZ[tz_name]
    if dst and _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1):
        hours += 1
    return timedelta(hours=hours)


def zone(tz_name, day):
    off = utc_offset(tz_name, day)
    return timezone(off) if off is not None else None


def is_business_day(d, holidays):
    return d.weekday() < 5 and d.isoformat() not in holidays


def add_business_days(start, n, holidays):
    """The date n business days after start (n=0 gives start, or the next business day if start is off)."""
    d = start
    while not is_business_day(d, holidays):
        d += timedelta(days=1)
    for _ in range(n):
        d += timedelta(days=1)
        while not is_business_day(d, holidays):
            d += timedelta(days=1)
    return d


def business_days_between(a, b, holidays):
    """Business days from a to b (a < b): how many steps forward a must move to reach b."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if is_business_day(d, holidays):
            n += 1
    return n


def next_business_day(d, holidays):
    return add_business_days(d + timedelta(days=1), 0, holidays)


def parse_ts(s, user_tz_name):
    """(aware datetime or None, problem or None). A timestamp needs a UTC offset."""
    raw = (s or "").strip()
    if not raw:
        return None, "blank timestamp"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, "timestamp is not ISO 8601"
    if dt.tzinfo is None:
        return None, "timestamp has no UTC offset"
    return dt, None


# ---------- loading ----------

class Workspace:
    def __init__(self, root, today):
        self.root = Path(root)
        self.today = today
        self.problems = []      # data problems, shown in every report
        cfg = {}
        p = self.root / "gtm.json"
        if p.exists():
            with open(p, encoding="utf-8-sig") as fh:
                cfg = json.load(fh)
        self.cfg = cfg
        self.d = deep_merge(DEFAULT_DAILY, cfg.get("daily", {}))
        self.shared = {k: cfg.get(k, v) for k, v in DEFAULT_SHARED.items()}
        self.exclude_rel = set((cfg.get("icp") or {}).get("exclude_relationships", DEFAULT_EXCLUDE_RELATIONSHIPS))
        self.dnc_notes = [x.lower() for x in (cfg.get("clean") or {}).get("dnc_note_patterns", DEFAULT_DNC_NOTES)]
        self.not_buyer = [re.compile(x, re.I) for x in self.shared["not_buyer_titles"]]
        self.holidays = set(self.d.get("holidays", []))
        owner = self.d.get("owner")
        if owner in (None, ""):
            owner = (cfg.get("play") or {}).get("owner") or "you"
        self.owner = str(owner).strip().lower()
        self.user_tz = self.d["user_timezone"]
        if utc_offset(self.user_tz, today) is None:
            raise ValueError(f"daily.user_timezone {self.user_tz!r} is not a known time zone")
        book = self.root / "book" / "people.csv"
        if not book.exists():
            raise ValueError("book/people.csv is missing. Build the book with account-book first.")
        self.people = {r["person_id"]: r for r in read_csv(book) if r.get("person_id")}
        acc = self.root / "book" / "accounts.csv"
        self.accounts = {r["account_id"]: r for r in read_csv(acc)} if acc.exists() else {}
        seq = self.root / "outreach" / "sequences.json"
        self.sequences = {}
        if seq.exists():
            with open(seq, encoding="utf-8-sig") as fh:
                for s in json.load(fh).get("sequences", []):
                    steps = sorted(s.get("steps", []), key=lambda x: (int(x.get("day", 1)), int(x.get("order", 1))))
                    self.sequences[s["id"]] = dict(s, steps=steps)
        self.signals = {}
        sig = self.root / "signals" / "scored.csv"
        if sig.exists():
            for r in read_csv(sig):
                if (r.get("playable") or "").lower() in ("yes", "true"):
                    self.signals[r.get("account_id", "")] = r
        self.log = self._load_log()
        self.enrollments = self._load_enrollments()
        self.calendar = self._load_calendar()

    def _load_log(self):
        path = self.root / "log" / "activity.csv"
        rows = []
        if not path.exists():
            return rows
        end_of_today = datetime.combine(self.today + timedelta(days=1), time(0), zone(self.user_tz, self.today))
        for r in read_csv(path):
            dt, prob = parse_ts(r.get("timestamp"), self.user_tz)
            if dt is not None and dt >= end_of_today:
                prob = "timestamp is after today"
                dt = None
            if prob:
                self.problems.append(f"log {r.get('activity_id') or '?'}: {prob}; treated as a blank time. "
                                     "The row still counts (a step it logs is worked, a stop outcome still stops), "
                                     "but its date is unknown")
            outcome = (r.get("outcome") or "").strip().lower()
            if outcome and outcome not in OUTCOMES:
                self.problems.append(f"log {r.get('activity_id') or '?'}: unknown outcome {outcome!r}; ignored")
                outcome = ""
            local_day = dt.astimezone(zone(self.user_tz, dt.date())).date() if dt else None
            pid, row_acct = r.get("person_id", ""), (r.get("account_id") or "").strip()
            book_acct = (self.people.get(pid) or {}).get("account_id", "")
            if book_acct and row_acct and book_acct != row_acct:
                self.problems.append(f"log {r.get('activity_id') or '?'}: person {pid} is at {book_acct} in the book "
                                     f"but the row says {row_acct}; the book's account is used")
            elif not book_acct and not row_acct:
                self.problems.append(f"log {r.get('activity_id') or '?'}: person {pid or '?'} is not in the book and "
                                     "the row has no account_id, so it cannot stop an account")
            rows.append(dict(r, _dt=dt, _day=local_day, _outcome=outcome, _acct=book_acct or row_acct,
                             _step=int(r["step"]) if (r.get("step") or "").strip().isdigit() else None))
        return rows

    def _load_enrollments(self):
        by_person = {}
        for path in sorted(glob.glob(str(self.root / "plays" / "*" / "enroll.csv"))):
            for r in read_csv(path):
                if (r.get("approved") or "").strip().lower() != "yes" or (r.get("drop_reason") or "").strip():
                    continue
                pid = r.get("person_id", "")
                if pid in by_person:
                    first = by_person[pid]
                    self.problems.append(f"{pid}: approved in two plays ({first['play_id']} and "
                                         f"{r.get('play_id')}); only {first['play_id']} is planned")
                    continue
                by_person[pid] = r
        return by_person

    def _load_calendar(self):
        path = self.root / "plan" / "calendar.csv"
        busy = []
        if not path.exists():
            return busy
        for r in read_csv(path):
            s, p1 = parse_ts(r.get("start"), self.user_tz)
            e, p2 = parse_ts(r.get("end"), self.user_tz)
            if p1 or p2 or s is None or e is None:
                self.problems.append(f"calendar row {r.get('title') or '?'!r}: {p1 or p2}; ignored. "
                                     "Times need a UTC offset, and a free/busy guess never books a call")
                continue
            busy.append((s, e, r.get("title", "")))
        return busy

    # account-level and person-level stop facts
    def outcomes_before(self, cutoff_day):
        """log rows that happened before cutoff_day (rows with a blank time always count)."""
        return [r for r in self.log if r["_day"] is None or r["_day"] < cutoff_day]


# ---------- sequence engine ----------

def fill(text, variables):
    missing = []

    def rep(m):
        v = variables.get(m.group(1))
        if v in (None, ""):
            missing.append(m.group(1))
            return m.group(0)
        return str(v)
    return VAR_RE.sub(rep, text or ""), missing


def person_vars(p, acct, enroll_vars):
    base = {"first_name": p.get("first_name", ""), "last_name": p.get("last_name", ""),
            "title": p.get("title", ""), "company": acct.get("name", "")}
    base.update({k: v for k, v in enroll_vars.items() if v not in (None, "")})
    return base


def _when(r):
    return r["_day"].isoformat() if r["_day"] else "an unknown date"


def lasting_stop(pid, log_rows):
    """The first log row with an outcome that ends every touch for the person, at any time, or None."""
    for r in log_rows:
        if r.get("person_id") == pid and r["_outcome"] in LASTING_STOP:
            return r
    return None


def bounced_row(pid, log_rows):
    for r in log_rows:
        if r.get("person_id") == pid and r["_outcome"] == "bounced":
            return r
    return None


def account_reply(ws, aid, pid, log_rows, since):
    """A reply-type outcome from someone else at the account (by the book's account) on or after `since`."""
    for r in log_rows:
        if (r["_outcome"] in ACCOUNT_STOP and r["_acct"] == aid and r.get("person_id") != pid
                and (r["_day"] is None or r["_day"] >= since)):
            return r
    return None


def owner_block(ws, acct):
    """'' when the account is yours to work (blank owner counts as yours), else the reason."""
    owner = (acct.get("owner") or "").strip()
    if owner and owner.lower() != ws.owner:
        return f"account owned by {owner}"
    return ""


BLOCKED_ACCOUNT_STATUSES = ("live_deal", "hold", "archived")


def account_status_block(ws, acct):
    """'' unless the account's own status stops all outbound. Checked whatever the
    book's strategy says: a live deal belongs to its owner."""
    status = (acct.get("status") or "").strip()
    if status in BLOCKED_ACCOUNT_STATUSES:
        return f"account status is {status}"
    return ""


def stop_reason(ws, p, enroll, log_rows, day):
    """Why the person's sequence stops, or ''."""
    status = (p.get("status") or "").strip()
    if status in ws.shared["stop_statuses"]:
        return f"status is {status}"
    tags = set(split_list(p.get("tags")))
    hit = sorted(tags & (set(ws.shared["dnc_tags"]) | set(ws.shared["left_tags"])))
    if hit:
        return f"tag {', '.join(hit)}"
    pid, aid = p.get("person_id"), p.get("account_id")
    r = lasting_stop(pid, log_rows)
    if r:
        return f"outcome {r['_outcome']} on {_when(r)}"
    owned = owner_block(ws, ws.accounts.get(aid, {})) or account_status_block(ws, ws.accounts.get(aid, {}))
    if owned:
        return owned
    start = parse_date(enroll.get("sequence_start")) or ws.today
    for r in log_rows:
        if r["_outcome"] in PERSON_STOP and r.get("person_id") == pid and (r["_day"] is None or r["_day"] >= start):
            return f"outcome {r['_outcome']} on {_when(r)}"
    since = min(start, day - timedelta(days=int(ws.d["reply_lookback_days"])))
    r = account_reply(ws, aid, pid, log_rows, since)
    if r:
        return f"someone at this account ({r.get('person_id')}) had outcome {r['_outcome']}: the account's sequences stop"
    return ""


def common_blocks(ws, p):
    """Person and account blocks that apply to every channel. Used for LinkedIn when
    the book has no linkedin_ok column, so an old book can never open that path."""
    reasons = []
    status = (p.get("status") or "").strip()
    if status in ws.shared["stop_statuses"]:
        reasons.append(f"status {status}")
    tags = set(split_list(p.get("tags")))
    hit = sorted(tags & (set(ws.shared["dnc_tags"]) | set(ws.shared["left_tags"])))
    if hit:
        reasons.append("tag " + ",".join(hit))
    notes = (p.get("notes") or "").lower()
    if any(x in notes for x in ws.dnc_notes):
        reasons.append("notes say do not contact")
    if any(rx.search(p.get("title") or "") for rx in ws.not_buyer):
        reasons.append("title is not a buyer")
    acct = ws.accounts.get(p.get("account_id", ""), {})
    rel = (acct.get("relationship") or "").strip()
    if rel and rel in ws.exclude_rel:
        reasons.append(f"account relationship is {rel}")
    strategy = (acct.get("strategy") or "").strip()
    if strategy in NO_OUTBOUND:
        reasons.append(f"account strategy is {strategy}")
    status_block = account_status_block(ws, acct)
    if status_block:
        reasons.append(status_block)
    return reasons


def channel_block(ws, p, channel, log_rows=()):
    """'' when the channel can be used for this person, else the reason."""
    tags = set(split_list(p.get("tags")))
    hit = sorted(tags & set(ws.shared["channel_block_tags"].get(channel, [])))
    if hit:
        return f"tag {', '.join(hit)}"
    if channel == "email":
        b = bounced_row(p.get("person_id"), log_rows)
        if b:
            return f"email bounced on {_when(b)}"
        s, f = (p.get("send_ok") or "").lower(), (p.get("followup_ok") or "").lower()
        if not s and not f:
            return "send gate not checked: rebuild the book with account-book"
        if s == "yes" or f == "yes":
            return ""
        return "send gate: " + (p.get("followup_block_reason") or p.get("send_block_reason") or "blocked")
    if channel == "call":
        c = (p.get("call_ok") or "").lower()
        if not c:
            return "call gate not checked: rebuild the book with account-book"
        if c != "yes":
            return "call gate: " + (p.get("call_block_reason") or "blocked")
        if not (p.get("phone") or "").strip():
            return "no phone"
        return ""
    if channel == "linkedin":
        li = (p.get("linkedin_ok") or "").lower()
        if li:
            if li != "yes":
                return "LinkedIn gate: " + (p.get("linkedin_block_reason") or "blocked")
        else:
            reasons = common_blocks(ws, p)
            if reasons:
                return "LinkedIn gate (checked here; rebuild the book for linkedin_ok): " + "; ".join(reasons)
        if not (p.get("linkedin_url") or "").strip():
            return "no LinkedIn profile"
        return ""
    return f"unknown channel {channel}"


def sequence_cards(ws, day):
    """Cards for sequence steps due on `day`, plus skipped and stopped lists."""
    log_rows = ws.outcomes_before(day)
    cards, skipped, stopped, waiting = [], [], [], []
    in_book_no_enroll = []
    for pid, p in sorted(ws.people.items()):
        if (p.get("sequence") or "").strip() and pid not in ws.enrollments:
            in_book_no_enroll.append(f"{pid}: the book says sequence {p['sequence']} but no approved enrollment "
                                     "with a start date exists, so it is not planned")
    for pid, e in sorted(ws.enrollments.items()):
        p = ws.people.get(pid)
        if p is None:
            ws.problems.append(f"{pid}: approved in {e.get('play_id')} but not in book/people.csv")
            continue
        acct = ws.accounts.get(p.get("account_id", ""), {})
        seq_id = e.get("sequence", "")
        seq = ws.sequences.get(seq_id)
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if seq is None:
            ws.problems.append(f"{pid}: sequence {seq_id!r} is not in outreach/sequences.json")
            continue
        start = parse_date(e.get("sequence_start"))
        if start is None:
            ws.problems.append(f"{pid}: enrollment in {e.get('play_id')} has no valid sequence_start")
            continue
        why = stop_reason(ws, p, e, log_rows, day)
        if why:
            stopped.append({"person_id": pid, "name": name, "sequence": seq_id, "reason": why})
            continue
        worked = {r["_step"] for r in log_rows if r.get("person_id") == pid and r.get("sequence") == seq_id
                  and r["_step"] is not None and (r.get("direction") or "out") == "out"}
        last = max(worked) if worked else 0
        steps = seq["steps"]
        if last >= len(steps):
            stopped.append({"person_id": pid, "name": name, "sequence": seq_id, "reason": "finished: every step worked"})
            continue
        try:
            enroll_vars = json.loads(e.get("variables") or "{}")
        except ValueError:
            enroll_vars = None
        # Steps worked late push every later step back by the same number of business days.
        offset = 0
        for j in range(1, last + 1):
            if j not in worked:
                continue
            due_j = add_business_days(start, int(steps[j - 1].get("day", 1)) - 1 + offset, ws.holidays)
            days_j = [r["_day"] for r in log_rows if r.get("person_id") == pid and r.get("sequence") == seq_id
                      and r["_step"] == j and r["_day"] is not None]
            if days_j and min(days_j) > due_j:
                offset += business_days_between(due_j, min(days_j), ws.holidays)
        k = last + 1
        while k <= len(steps):
            step = steps[k - 1]
            due = add_business_days(start, int(step.get("day", 1)) - 1 + offset, ws.holidays)
            block = channel_block(ws, p, step.get("channel", ""), log_rows)
            if block:
                if due <= day:
                    skipped.append({"person_id": pid, "name": name, "sequence": seq_id, "step": k,
                                    "channel": step.get("channel"), "due": due.isoformat(), "reason": block})
                    k += 1
                    continue
                waiting.append(pid)
                break
            if due > day:
                waiting.append(pid)
                break
            shift = business_days_between(due, day, ws.holidays)
            note = f"step {k} was due {due.isoformat()}; it and later steps move {shift} business day(s)" if shift else ""
            if enroll_vars is None:
                status, missing = "needs_human", ["variables (not valid JSON)"]
                subject, body = step.get("subject", ""), step.get("body", "")
            else:
                vs = person_vars(p, acct, enroll_vars)
                subject, m1 = fill(step.get("subject", ""), vs)
                body, m2 = fill(step.get("body", ""), vs)
                missing = sorted(set(m1 + m2))
                status = "needs_human" if missing else "ready"
            channel = step.get("channel", "")
            cards.append({
                "kind": "sequence", "block": "sequence", "person_id": pid, "account_id": p.get("account_id", ""),
                "name": name, "title": p.get("title", ""), "account": acct.get("name", ""), "channel": channel,
                "sequence": seq_id, "step": str(k), "play_id": e.get("play_id", ""), "status": status,
                "prep": body if channel == "call" else "", "subject": subject if channel == "email" else "",
                "body": "" if channel == "call" else body, "score": "", "timezone": p.get("timezone", ""),
                "why": "; ".join(x for x in [note, ("fill: " + ", ".join(missing)) if missing else ""] if x),
                "thread": step.get("thread", ""), "skip_reason": "",
                "copy": TEMPLATE_NOTE if channel == "email" and body else "",
                "source": quoted_source(enroll_vars, body),
            })
            break
        else:
            stopped.append({"person_id": pid, "name": name, "sequence": seq_id,
                            "reason": "finished: no doable steps left"})
    ws.problems.extend(in_book_no_enroll)
    return cards, skipped, stopped


# ---------- weighted queue for extra touches ----------

def seniority(title):
    t = (title or "").lower()
    for pat, n in SENIOR:
        if re.search(pat, t):
            return n
    return 0


def last_touch(ws, pid, log_rows, p):
    days = [r["_day"] for r in log_rows if r.get("person_id") == pid and r["_day"] is not None
            and (r.get("direction") or "out") == "out"]
    book_day = parse_date(p.get("last_touch_date"))
    if book_day:
        days.append(book_day)
    if any(r.get("person_id") == pid and r["_day"] is None for r in log_rows):
        return "unknown"
    return max(days) if days else None


def recency_score(ws, last, day):
    if last is None:
        return ws.d["never_touched_recency"]
    if last == "unknown":
        return 0.0
    age = (day - last).days
    lo, hi = ws.d["recency_peak_days"]
    if age < lo:
        return 0.0
    if age <= hi:
        return 1.0
    return max(0.3, 1.0 - (age - hi) / 60.0)


def extra_cards(ws, day, taken):
    log_rows = ws.outcomes_before(day)
    since = day - timedelta(days=int(ws.d["reply_lookback_days"]))
    replied_accounts = {r["_acct"] for r in log_rows
                        if r["_outcome"] in ACCOUNT_STOP and (r["_day"] is None or r["_day"] >= since)}
    active_by_acct = {}
    for pid in ws.enrollments:
        p = ws.people.get(pid)
        if p:
            active_by_acct.setdefault(p.get("account_id"), set()).add(pid)
    max_signal = max([float(s.get("score") or 0) for s in ws.signals.values()] or [0]) or 1.0
    w = ws.d["weights"]
    gate = ws.cfg.get("send_gate", {})
    min_score = gate.get("min_email_score") or 0
    cands, dropped = [], {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for pid, p in sorted(ws.people.items()):
        if pid in taken or pid in ws.enrollments or (p.get("sequence") or "").strip():
            continue
        if (p.get("status") or "") in ws.shared["stop_statuses"]:
            drop("stop status")
            continue
        tags = set(split_list(p.get("tags")))
        if tags & (set(ws.shared["dnc_tags"]) | set(ws.shared["left_tags"])):
            drop("do-not-contact or left tag")
            continue
        if lasting_stop(pid, log_rows):
            drop("log outcome ends every touch (opt out, not interested, wrong person or left)")
            continue
        aid = p.get("account_id", "")
        if owner_block(ws, ws.accounts.get(aid, {})):
            drop("account owned by someone else")
            continue
        status_block = account_status_block(ws, ws.accounts.get(aid, {}))
        if status_block:
            drop(status_block)
            continue
        if aid in replied_accounts:
            drop("someone at the account replied: a person handles it")
            continue
        last = last_touch(ws, pid, log_rows, p)
        if last not in (None, "unknown") and (day - last).days < ws.d["min_days_between_touches"]:
            drop("touched too recently")
            continue
        call_ok = not channel_block(ws, p, "call")
        # LinkedIn-only: no usable phone and no email path, but a profile to message.
        li_ok = (not call_ok and (p.get("send_ok") or "").lower() != "yes"
                 and not channel_block(ws, p, "linkedin"))
        if not call_ok and not li_ok:
            drop("no usable channel for an extra touch")
            continue
        channel = "call" if call_ok else "linkedin"
        acct = ws.accounts.get(aid, {})
        if tags & set(ws.d["inbound_tags"]) and last is None:
            block = "inbound"
        elif tags & set(ws.d["warm_tags"]):
            block = "warm"
        elif channel == "linkedin":
            block = "linkedin_only"
        else:
            block = "volume"
        sig = ws.signals.get(aid)
        es = (p.get("email_status") or "").lower()
        try:
            esc = float(p.get("email_score") or 0)
        except ValueError:
            esc = 0.0
        if es == "verified" and esc >= min_score:
            deliver = 1.0
        elif es in ("risky", "catch_all"):
            deliver = 0.3
        elif (p.get("phone") or "").strip():
            deliver = 0.5
        else:
            deliver = 0.0
        nxt = p.get("next_step") or ""
        due = 1.0 if parse_date(nxt) and parse_date(nxt) <= day else 0.0
        others = active_by_acct.get(aid, set()) - {pid}
        sub = {
            "signal": (float(sig.get("score") or 0) / max_signal) if sig else 0.0,
            "seat": ROLE_SCORE.get(p.get("role", ""), 0.2),
            "recency": recency_score(ws, last, day),
            "fit": TIER_SCORE.get(acct.get("tier", ""), 0.3),
            "due_step": due,
            "single_threaded": 1.0 if len(others) == 1 else 0.0,
            "deliverability": deliver,
        }
        total = sum(w.get(k, 0) for k in sub) or 1
        score = sum(w.get(k, 0) * v for k, v in sub.items()) / total
        prep = ""
        if sig:
            prep = sig.get("why_now", "")
        elif nxt and not parse_date(nxt):
            prep = nxt
        elif (p.get("notes") or "").strip():
            prep = (p.get("notes") or "").strip().splitlines()[-1]
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        cands.append({
            "kind": "extra", "block": block, "person_id": pid, "account_id": aid, "name": name,
            "title": p.get("title", ""), "account": acct.get("name", ""), "channel": channel, "sequence": "",
            "step": "", "play_id": "", "status": "ready" if prep else "no_prep", "prep": prep, "subject": "",
            "body": "", "score": round(score, 3), "timezone": p.get("timezone", ""), "skip_reason": "",
            "score_parts": ", ".join(f"{k} {sub[k]:.2f}x{w.get(k, 0)}" for k in sorted(sub)),
            "why": "never touched" if last is None else ("last touch unknown" if last == "unknown" else f"last touch {last.isoformat()}"),
            "_facts": {
                "inbound_untouched": 1 if block == "inbound" else 0,
                "never_touched": 1 if last is None else 0,
                "buying_role": ROLE_SCORE.get(p.get("role", ""), 0.2),
                "seniority": seniority(p.get("title")),
                "has_deal": 1 if (acct.get("status") or "") == "live_deal" else 0,
                "newest": pid,
            },
        })
    flat = False
    if len(cands) >= 2:
        scores = [c["score"] for c in cands]
        flat = (max(scores) - min(scores)) < ws.d["flat_gap"]
    order = {b: i for i, b in enumerate(ws.d["block_order"])}
    chan_pref = {"call": 0, "linkedin": 1}
    if flat:
        ladder = ws.d["fact_ladder"]
        rank = lambda c: (tuple((-c["_facts"][f] if isinstance(c["_facts"][f], (int, float)) else "")
                                for f in ladder if f != "newest"), _neg_str(c["_facts"]["newest"]))
    else:
        rank = lambda c: (-c["score"], c["person_id"])
    # Who gets the account's slots: a card with a prep line first, then a call over LinkedIn, then the
    # score (or the fact ladder when scores are flat). Block order only decides how the plan is shown.
    cands.sort(key=lambda c: (c["status"] == "no_prep", chan_pref.get(c["channel"], 2), rank(c)))
    per_acct, out = {}, []
    for c in cands:
        if per_acct.get(c["account_id"], 0) >= ws.d["extras_per_account"]:
            drop("account already has an extra card today")
            continue
        if len(out) >= ws.d["max_extra_cards"]:
            drop("over the daily extra-card cap")
            continue
        per_acct[c["account_id"]] = per_acct.get(c["account_id"], 0) + 1
        out.append(c)
    out.sort(key=lambda c: (order.get(c["block"], 99), c["status"] == "no_prep", rank(c)))
    for c in out:
        if flat:
            c["score"] = ""
            c["score_parts"] = ""
    return out, dropped, flat


def _neg_str(s):
    """Sort key that puts a larger string first."""
    return tuple(-ord(ch) for ch in s)


# ---------- call blocks ----------

def assign_calls(ws, day, cards):
    """Two-pass fill of call cards into the user's call blocks by the prospect's local time."""
    utz = zone(ws.user_tz, day)
    slot = timedelta(minutes=int(ws.d["call_slot_minutes"]))
    all_slots = []
    for b in ws.d["call_blocks"]:
        t = datetime.combine(day, parse_hhmm(b["start"]), utz)
        end = datetime.combine(day, parse_hhmm(b["end"]), utz)
        while t + slot <= end:
            busy = any(s < t + slot and t < e for s, e, _ in ws.calendar)
            all_slots.append({"block": b["name"], "start": t, "card": None, "busy": busy})
            t += slot
    slots = [s for s in all_slots if not s["busy"]]
    win = (parse_hhmm(ws.d["call_window"]["start"]), parse_hhmm(ws.d["call_window"]["end"]))
    pref = (parse_hhmm(ws.d["preferred_window"]["start"]), parse_hhmm(ws.d["preferred_window"]["end"]))
    calls = [c for c in cards if c["channel"] == "call" and c["status"] in ("ready", "no_prep", "needs_human")]
    pending = []
    for c in calls:
        ptz = zone(c["timezone"], day) if c.get("timezone") else None
        if ptz is None:
            c["status"] = "needs_human"
            c["why"] = "; ".join(x for x in [c["why"], "time zone unknown: check local time before dialing"] if x)
            continue
        c["_ptz"] = ptz
        pending.append(c)

    def fits(c, s, window):
        lo = (s["start"].astimezone(c["_ptz"])).time()
        hi = (s["start"] + slot).astimezone(c["_ptz"]).time()
        return window[0] <= lo and hi <= window[1] and lo < hi

    for window in (pref, win):
        for c in pending:
            if c.get("_slot"):
                continue
            for s in slots:
                if s["card"] is None and fits(c, s, window):
                    s["card"] = c
                    c["_slot"] = s
                    break
    for c in pending:
        s = c.get("_slot")
        if s:
            c["slot_start"] = s["start"].strftime("%H:%M") + f" {ws.user_tz}"
            c["prospect_local"] = s["start"].astimezone(c["_ptz"]).strftime("%H:%M") + f" {c['timezone']}"
            c["call_block"] = s["block"]
        else:
            legal = any(fits(c, s, win) for s in all_slots)
            if legal:
                c["status"] = "overflow"
                c["why"] = "; ".join(x for x in [c["why"], "no call slot left today: carry to tomorrow"] if x)
            else:
                c["status"] = "skipped"
                c["skip_reason"] = "outside calling hours: none of today's call blocks fall inside 8am to 9pm their time"


# ---------- plan ----------

def build_plan(ws, day):
    seq, skipped, stopped = sequence_cards(ws, day)
    extras, dropped, flat = extra_cards(ws, day, {c["person_id"] for c in seq})
    cards = seq + extras
    assign_calls(ws, day, cards)
    for c in cards:
        if c["status"] == "skipped" and c["kind"] == "sequence":
            skipped.append({"person_id": c["person_id"], "name": c["name"], "sequence": c["sequence"],
                            "step": c["step"], "channel": "call", "due": day.isoformat(), "reason": c["skip_reason"]})
    live = [c for c in cards if c["status"] != "skipped"]
    chan_rank = {"email": 0, "linkedin": 1, "call": 2}
    inbound = [c for c in live if c["kind"] == "extra" and c["block"] == "inbound"]
    seq_live = sorted([c for c in live if c["kind"] == "sequence"],
                      key=lambda c: (chan_rank.get(c["channel"], 3), c.get("slot_start") or "99", c["person_id"]))
    rest = [c for c in live if c["kind"] == "extra" and c["block"] != "inbound"]
    ordered = inbound + seq_live + rest
    for i, c in enumerate(ordered, 1):
        c["order"] = i
        c["card_id"] = f"{day.isoformat()}-{i:03d}"
        c["date"] = day.isoformat()
    return {"cards": ordered, "skipped": skipped, "stopped": stopped, "dropped": dropped, "flat": flat}


def first_action(plan):
    """One line: the first ready card you can do now, plus the first call and its time."""
    ready = [c for c in plan["cards"] if c["status"] == "ready"]
    if not ready:
        if any(c["status"] == "needs_human" for c in plan["cards"]):
            return "Do first: fill the cards marked needs_human; nothing is ready as it is."
        if plan["cards"] and all(c["status"] == "no_prep" for c in plan["cards"]):
            return ("Do first: find one real reason for each no_prep card (no prep line, no dial); "
                    "nothing is ready as it is.")
        if plan["cards"]:
            return "Do first: nothing is ready as it is; read the card statuses below."
        return "Do first: nothing is due today. Check plays for approvals."

    def label(c):
        what = f"{c['channel']} {c['name']} ({c['account']})"
        if c["kind"] == "sequence":
            what += f", {c['sequence']} step {c['step']}"
        return what
    now = [c for c in ready if c["channel"] != "call"]
    calls = sorted([c for c in ready if c["channel"] == "call" and c.get("slot_start")],
                   key=lambda c: (c["slot_start"], c["order"]))
    if now and calls:
        return f"Do first: {label(now[0])}. First call: {label(calls[0])} at {calls[0]['slot_start']}."
    if now:
        return f"Do first: {label(now[0])}."
    if calls:
        return f"Do first: {label(calls[0])} at {calls[0]['slot_start']}."
    return f"Do first: {label(ready[0])}."


def card_md(c):
    lines = [f"### {c['card_id']} | {c['name']}, {c['title']}, {c['account']}",
             f"- channel: {c['channel']}" + (f" | {c['sequence']} step {c['step']}" if c["sequence"] else ""),
             f"- status: {c['status']}"]
    if c.get("slot_start"):
        lines.append(f"- slot: {c['slot_start']} (their time {c['prospect_local']})")
    if c.get("score") not in ("", None):
        lines.append(f"- score: {c['score']}" + (f" (parts, value x weight: {c['score_parts']})"
                                                  if c.get("score_parts") else ""))
    if c.get("why"):
        lines.append(f"- why: {c['why']}")
    if c.get("prep"):
        lines.append(f"- prep: {c['prep']}")
    if c.get("subject"):
        lines.append(f"- subject: {c['subject']}")
    if c.get("body"):
        lines.append(f"- body: {c['body']}")
    if c.get("copy"):
        lines.append(f"- copy: {c['copy']}")
    if c.get("source"):
        lines.append(f"- source: {c['source']} (open it before this touch; if it is gone or says something "
                     "else, do not use the fact)")
    lines += ["- [ ] done", "- outcome:", ""]
    return "\n".join(lines)


def today_in_user_zone(root):
    """Today's date in daily.user_timezone (the D1 stated default for a read-only plan)."""
    tz = DEFAULT_DAILY["user_timezone"]
    path = root / "gtm.json"
    if path.exists():
        try:
            tz = (json.loads(path.read_text(encoding="utf-8")).get("daily") or {}).get("user_timezone") or tz
        except json.JSONDecodeError:
            pass
    now = datetime.now(timezone.utc)
    return (now + utc_offset(tz, now.date())).date(), tz


def render_plan(ws, day, plan):
    cards = plan["cards"]
    off = utc_offset(ws.user_tz, day)
    hours = off.total_seconds() / 3600
    out = [f"# Plan for {day.isoformat()}", "",
           f"Your time zone: {ws.user_tz} (UTC{hours:+g}). Call times below are in your time zone, with the "
           "prospect's local time beside them.", "",
           *([plan["date_note"], ""] if plan.get("date_note") else []),
           first_action(plan), "",
           f"Cards: {len(cards)} ({sum(c['kind'] == 'sequence' for c in cards)} sequence steps, "
           f"{sum(c['kind'] == 'extra' for c in cards)} extra touches). "
           f"Needs you: {sum(c['status'] == 'needs_human' for c in cards)}. "
           f"Skipped steps: {len(plan['skipped'])}. Stopped sequences: {len(plan['stopped'])}."
           + (f" Entries kept from the last run that no longer match a card: {len(plan['orphans'])}."
              if plan.get("orphans") else ""), "",
           "Nothing here has been sent or dialed. Log each outcome in log/activity.csv; tonight run the close.", ""]
    if plan.get("kept"):
        out += [f"This is a rerun: {plan['kept']} entr{'y' if plan['kept'] == 1 else 'ies'} you wrote in the plan CSV "
                "(skip reasons or your own columns) were kept.", ""]
    if plan.get("orphans"):
        out += ["## Entries kept from the last run that no longer match a card", "",
                "You wrote these in the plan CSV, but today's rerun has no card for them any more (the person moved "
                "to another card, was stopped, or the plan changed). They are kept in "
                f"plan/{day.isoformat()}-unmatched.csv and go back onto their card if it returns.", ""]
        for r in plan["orphans"]:
            step = f" step {r.get('step')}" if r.get("step") else ""
            seq = f" {r.get('sequence')}" if r.get("sequence") else ""
            out.append(f"- {r.get('card_id', '')} | {r.get('name') or r.get('person_id', '')} | "
                       f"{r.get('kind', '')}{seq}{step} {r.get('channel', '')} | {r['entries']}")
        out.append("")
    groups = [("Inbound never worked", lambda c: c["kind"] == "extra" and c["block"] == "inbound"),
              ("Sequence steps due today", lambda c: c["kind"] == "sequence"),
              ("Warm", lambda c: c["kind"] == "extra" and c["block"] == "warm"),
              ("LinkedIn only", lambda c: c["kind"] == "extra" and c["block"] == "linkedin_only"),
              ("Volume", lambda c: c["kind"] == "extra" and c["block"] == "volume")]
    for title, pred in groups:
        sel = [c for c in cards if pred(c)]
        if not sel:
            continue
        out += [f"## {title}", ""]
        if title != "Sequence steps due today" and plan["flat"]:
            out += ["The scores were too close to mean anything, so these are ordered by plain facts "
                    "(inbound and untouched first, then never touched, buying role, seniority, open deal, newest).", ""]
        out += [card_md(c) for c in sel]
    if plan["skipped"]:
        out += ["## Skipped steps (not missed: they could not be done)", "",
                "| person | sequence | step | channel | due | reason |", "|---|---|---|---|---|---|"]
        out += [f"| {s['name']} ({s['person_id']}) | {s['sequence']} | {s['step']} | {s['channel']} | {s['due']} | {s['reason']} |"
                for s in plan["skipped"]]
        out.append("")
    if plan["stopped"]:
        out += ["## Stopped sequences", "", "| person | sequence | reason |", "|---|---|---|"]
        out += [f"| {s['name']} ({s['person_id']}) | {s['sequence']} | {s['reason']} |" for s in plan["stopped"]]
        out.append("")
    if plan["dropped"]:
        out += ["## Left out of extra touches", ""]
        out += [f"- {k}: {v}" for k, v in sorted(plan["dropped"].items())]
        out.append("")
    out += ["## Data problems", ""]
    out += [f"- {p}" for p in ws.problems] or ["- none"]
    out.append("")
    return "\n".join(out)


# ---------- reruns ----------

def card_key(c):
    return (c.get("person_id", ""), c.get("kind", ""), c.get("sequence", ""), str(c.get("step", "")), c.get("channel", ""))


def _read_rows(path):
    if not path.exists():
        return [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return [dict(r) for r in reader], list(reader.fieldnames or [])


def _user_entries(r, extra_cols):
    """What the user wrote on one old plan row: a skip_reason the plan did not set, and added columns."""
    got = {}
    if (r.get("skip_reason") or "").strip() and r.get("status") != "skipped":
        got["skip_reason"] = r["skip_reason"].strip()
    for col in extra_cols:
        if (r.get(col) or "").strip():
            got[col] = r[col].strip()
    return got


def merge_user_entries(path, cards, unmatched_path=None):
    """Carry what the user wrote in an existing plan CSV into a same-day rerun: skip_reason on cards that
    were not skipped by the plan itself, and any column the user added. Entries whose card no longer exists
    are returned as orphans (and kept in unmatched_path) so they never vanish silently; one that matches a
    card again on a later rerun goes back onto it. Returns (columns, entries kept, orphans)."""
    old, header = _read_rows(path)
    parked, parked_header = _read_rows(unmatched_path) if unmatched_path else ([], [])
    extra_cols = [c for c in header + parked_header if c not in PLAN_COLS and c != "entries"]
    extra_cols = list(dict.fromkeys(extra_cols))
    current = {card_key(c): c for c in cards}
    kept, orphans, seen = 0, [], set()
    for r in old + parked:
        key = card_key(r)
        if key in seen:
            continue
        mine = _user_entries(r, extra_cols)
        if not mine:
            continue
        seen.add(key)
        c = current.get(key)
        if c is None:
            orphans.append(dict(r, entries="; ".join(f"{k}: {v}" for k, v in mine.items())))
            continue
        if "skip_reason" in mine and c.get("status") != "skipped" and not c.get("skip_reason"):
            c["skip_reason"] = mine["skip_reason"]
            kept += 1
        for col in extra_cols:
            if col in mine:
                c[col] = mine[col]
                kept += 1
    return PLAN_COLS + extra_cols, kept, orphans


# ---------- close ----------

COMMIT_RE = re.compile(r"\b(we owe|they owe)\s*:\s*(.+?)(?:\s+by\s+(\d{4}-\d{2}-\d{2}))?\s*$", re.I)


def close_day(ws, day):
    path = ws.root / "plan" / f"{day.isoformat()}.csv"
    if not path.exists():
        raise ValueError(f"plan/{day.isoformat()}.csv is missing: there is no plan to close")
    cards = read_csv(path)
    today_rows = [r for r in ws.log if r["_day"] == day and (r.get("direction") or "out") == "out"]
    done, skipped, missing, carried = [], [], [], []
    for c in cards:
        if c.get("status") == "skipped":
            continue
        if c.get("status") == "overflow":
            carried.append(c)
            continue
        match = [r for r in today_rows if r.get("person_id") == c["person_id"] and r.get("channel") == c["channel"]
                 and (not c.get("sequence") or (r.get("sequence") == c["sequence"] and str(r["_step"]) == c.get("step")))]
        if match:
            done.append((c, match[-1]["_outcome"] or "logged"))
        elif (c.get("skip_reason") or "").strip():
            skipped.append(c)
        else:
            missing.append(c)
    commitments = []
    for r in ws.log:
        if r["_day"] != day:
            continue
        for line in (r.get("notes") or "").split(";"):
            m = COMMIT_RE.search(line.strip())
            if m:
                commitments.append({"who": m.group(1).lower(), "what": m.group(2).strip(), "by": m.group(3) or "no date",
                                    "person_id": r.get("person_id", "")})
    nxt = next_business_day(day, ws.holidays)
    ws2 = Workspace(ws.root, nxt)
    tomorrow = build_plan(ws2, nxt)
    top = [c for c in tomorrow["cards"] if c["status"] == "ready"][:3]
    out = [f"# Close for {day.isoformat()}", "",
           f"Planned cards: {len(cards)}. Done: {len(done)}. Skipped with a reason: {len(skipped)}. "
           f"Carried to tomorrow (no call slot): {len(carried)}. No record: {len(missing)}.", ""]
    if missing:
        out += ["## No record (fix these first)", "",
                "Each card below has no log row today and no skip reason. Log what happened, or write a "
                "skip_reason in the plan CSV, then rerun the close.", ""]
        out += [f"- {c['card_id']} | {c['name']} | {c['channel']}" + (f" | {c['sequence']} step {c['step']}" if c.get("sequence") else "")
                for c in missing]
        out.append("")
    if done:
        out += ["## Done", ""] + [f"- {c['card_id']} | {c['name']} | {c['channel']} | {o}" for c, o in done] + [""]
    if skipped:
        out += ["## Skipped", ""] + [f"- {c['card_id']} | {c['name']} | {c['skip_reason']}" for c in skipped] + [""]
    if carried:
        out += ["## Carried to tomorrow", ""] + [f"- {c['card_id']} | {c['name']} | {c['channel']}" for c in carried] + [""]
    out += ["## Commitments", ""]
    if commitments:
        out += ["| who | what | by | person |", "|---|---|---|---|"]
        out += [f"| {c['who']} | {c['what']} | {c['by']} | {c['person_id']} |"
                for c in sorted(commitments, key=lambda x: (x["by"], x["who"]))]
    else:
        out.append("- none logged today (write \"we owe: ...\" or \"they owe: ... by YYYY-MM-DD\" in a log note)")
    out += ["", f"## Tomorrow's top 3 ({nxt.isoformat()})", ""]
    out += [f"{i}. {c['channel']} {c['name']} ({c['account']})" + (f", {c['sequence']} step {c['step']}" if c["sequence"] else "")
            for i, c in enumerate(top, 1)] or ["- nothing ready yet"]
    probs = sorted(set(ws.problems))
    out += ["", "## Data problems", ""] + ([f"- {p}" for p in probs] or ["- none"]) + [""]
    return "\n".join(out), {"done": len(done), "skipped": len(skipped), "no_record": len(missing),
                            "commitments": len(commitments)}


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan today's touches from approved enrollments, or close the day.")
    ap.add_argument("--workspace", default="gtm")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today in daily.user_timezone, and the plan says so)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--close", action="store_true", help="close the day instead of planning it")
    mode.add_argument("--nudge", action="store_true", help="print one line: what to do first, or FAILED: why")
    args = ap.parse_args(argv)
    date_note = ""
    if args.today:
        day = parse_date(args.today)
        if day is None:
            ap.error("--today must be YYYY-MM-DD")
    else:
        day, tz = today_in_user_zone(Path(args.workspace))
        date_note = f"No date was given, so this is the plan for today, {day.isoformat()} in {tz}."
    try:
        ws = Workspace(args.workspace, day)
        if args.nudge:
            if not is_business_day(day, ws.holidays):
                print(f"Do first: nothing. {day.isoformat()} is not a business day.")
                return 0
            print(first_action(build_plan(ws, day)))
            return 0
        plan_dir = ws.root / "plan"
        plan_dir.mkdir(exist_ok=True)
        if args.close:
            text, counts = close_day(ws, day)
            target = plan_dir / f"{day.isoformat()}-close.md"
            target.write_text(text, encoding="utf-8")
            print(f"Closed {day.isoformat()}: done {counts['done']}, skipped {counts['skipped']}, "
                  f"no record {counts['no_record']}, commitments {counts['commitments']}.")
            print(f"Wrote {target}")
            if counts["no_record"]:
                print("Some cards have no record. Log them or write a skip_reason, then rerun the close.")
            return 0
        if not is_business_day(day, ws.holidays):
            print(f"{day.isoformat()} is not a business day. Nothing planned.")
            return 0
        plan = build_plan(ws, day)
        plan["date_note"] = date_note
        md = plan_dir / f"{day.isoformat()}.md"
        cv = plan_dir / f"{day.isoformat()}.csv"
        parked = plan_dir / f"{day.isoformat()}-unmatched.csv"
        cols, kept, orphans = merge_user_entries(cv, plan["cards"], parked)
        plan["kept"] = kept
        plan["orphans"] = orphans
        if orphans:
            write_csv(parked, orphans, cols + ["entries"])
        elif parked.exists():
            parked.unlink()  # every parked entry found its card again
        md.write_text(render_plan(ws, day, plan), encoding="utf-8")
        write_csv(cv, plan["cards"], cols)
        if kept:
            print(f"Kept {kept} entr{'y' if kept == 1 else 'ies'} you wrote in {cv.name} (skip reasons or your own columns).")
        if orphans:
            print(f"{len(orphans)} entr{'y' if len(orphans) == 1 else 'ies'} you wrote no longer "
                  f"match{'es' if len(orphans) == 1 else ''} a card; "
                  f"listed in the plan and kept in {parked.name}.")
        print(first_action(plan))
        print(f"Cards: {len(plan['cards'])}; skipped steps: {len(plan['skipped'])}; "
              f"stopped sequences: {len(plan['stopped'])}; data problems: {len(ws.problems)}.")
        print(f"Wrote {md} and {cv}")
        print("Nothing was sent, dialed, enrolled or written to a CRM.")
        return 0
    except (ValueError, OSError) as exc:
        if args.nudge:
            print(f"FAILED: {exc}")
            return 1
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
