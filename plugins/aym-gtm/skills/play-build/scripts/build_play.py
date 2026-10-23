#!/usr/bin/env python3
"""Fill one play: who qualifies, who at each account, which day they start.

Reads the book (book/people.csv, book/accounts.csv), gtm.json, the play
definition (plays/<id>/play.json) and, depending on the play type,
signals/scored.csv, an events CSV, log/activity.csv and outreach/sequences.json.

Writes only inside plays/<id>/:
  enroll.csv   proposed enrollments (approved blank until you write yes) and
               every in-scope person who was dropped, with the reason
  funnel.md    the eligibility funnel: count at the start, count removed by
               each rule with reasons, count at the end
  report.md    what needs you, rule-change ideas, whether the play still finds people
  state.json   one line per run day, used to spot a play that stopped finding people

It never enrolls anyone in a real tool, never sends and never writes to a CRM.
Standard library only. Python 3.8+.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

DEFAULT_PLAY = {
    "daily_cap": 5,
    "holdout_share": 0,
    "per_account_cap": 1,
    "recent_touch_days": 14,
    "owner": "you",
    "seat_order": ["decision_maker", "champion", "influencer", "technical_gatekeeper"],
    "signal_seat_roles": {
        "new_leader": ["named", "decision_maker", "champion"],
        "leader_gap": ["decision_maker", "champion"],
        "hiring": ["champion", "decision_maker"],
        "funding": ["decision_maker", "champion"],
        "topic_intent": ["decision_maker", "champion"],
        "growth": ["decision_maker", "champion"],
    },
    "max_quiet_runs": 3,
    "default_sequence_days": 10,
    "stop_outcomes": ["opt_out", "not_interested", "wrong_person", "left"],
    "email_stop_outcomes": ["bounced"],
    "conversation_outcomes": ["replied", "interested", "not_now", "booked"],
    "conversation_days": 30,
    "tier_points": {"P1": 3, "P2": 2, "P3": 1},
    "event": {"invites_per_account": 2, "finish_days_before": 2, "file": "input/events.csv"},
    "reactivation": {"min_quiet_days": 60, "gap_factor": 1.5, "default_interval_days": 90,
                     "account_tags": ["lost_deal"], "recent_touch_days": 14},
    "multithread": {"engaged_outcomes": ["replied", "interested", "not_now", "booked", "connected"],
                    "per_account_cap": 2},
    "override_conversation_words": ["demo", "asked", "requested", "replied", "reply", "meeting",
                                    "call back", "intro"],
}
DEFAULT_STOP = ["hold", "booked", "not_interested", "wrong_person", "left", "do_not_contact", "archived"]
DEFAULT_DNC = ["opted_out", "dnc_all"]
DEFAULT_LEFT = ["moved"]
BLOCKED_STRATEGIES = {"excluded", "hold", "live"}
# Checked on the account's own status too, whatever the book's strategy says: a live
# deal belongs to its owner even if the book ranked a past reply above it.
BLOCKED_ACCOUNT_STATUSES = {"live_deal", "hold", "archived"}


def account_block(a):
    status = (a.get("status") or "").strip()
    if status in BLOCKED_ACCOUNT_STATUSES:
        return f"account status {status}"
    if a.get("strategy") in BLOCKED_STRATEGIES:
        return f"account strategy {a.get('strategy')}"
    return ""
TYPES = ("signal", "event", "reactivation", "multithread", "blitz")
OUTPUTS = ("enroll.csv", "funnel.md", "report.md", "state.json")
ENROLL_COLS = ["play_id", "person_id", "account_id", "seat", "sequence", "sequence_start",
               "variables", "rank", "approved", "drop_reason"]


# ---------- small helpers ----------


def trigger_fact(company, why_now):
    """A why-now line as a clause that reads after "I saw": the account name, then
    the source's fact with its first letter lowered. Signal summaries usually start
    with a verb ("Posted an opening for..."), so they need a subject."""
    fact = re.sub(r"\s*\(source dated [^)]*\)\.?\s*$", "", (why_now or "").strip()).strip().rstrip(".")
    if not fact:
        return ""
    name = (company or "").strip()
    if not name or fact.lower().startswith(name.lower()):
        return fact
    first = fact[0].lower() if not (len(fact) > 1 and fact[1].isupper()) else fact[0]
    return f"{name} {first}{fact[1:]}"

def you_fact(company, why_now, first_name, last_name):
    """The trigger fact for the person the signal names. The line is written to them, so it says
    "you": "Brightmill Manufacturing named you Chief Financial Officer", never their name."""
    full = " ".join(x for x in ((first_name or "").strip(), (last_name or "").strip()) if x)
    fact = re.sub(r"\s*\(source dated [^)]*\)\.?\s*$", "", (why_now or "").strip()).strip().rstrip(".")
    if not full or not re.search(r"\b" + re.escape(full) + r"\b", fact, re.I):
        return trigger_fact(company, why_now)
    name = re.escape(full)
    fact = re.sub(r"\b(named|appointed) " + name + r",? as\b", r"\1 you", fact, flags=re.I)
    fact = re.sub(r"\b" + name + r"'s\b", "your", fact, flags=re.I)
    fact = re.sub(r"\b" + name + r"\b", "you", fact, flags=re.I)
    if fact.lower().startswith(("you ", "your ")):
        return "y" + fact[1:]
    return trigger_fact(company, fact)


def conversation_word(reason, words):
    """The first word from `words` found at the start of a word in an override reason, or "".
    A listed word ending in "ed" also matches its other forms: "requested" finds "requests",
    "replied" finds "replies", "intro" finds "introduced"."""
    text = norm(reason)
    for w in words or []:
        w = norm(w)
        if not w:
            continue
        stem = w[:-2] if w.endswith("ed") and len(w) > 4 else w
        if re.search(r"\b" + re.escape(stem).replace(r"\ ", r"\s+"), text):
            return w
    return ""


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
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def write_csv(path, rows, cols):
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def split_list(value):
    return [x.strip() for x in str(value or "").split(";") if x.strip()]


def to_num(value, default=None):
    text = str(value or "").replace(",", "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def parse_day(value):
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def full_name(p):
    return norm(f"{p.get('first_name', '')} {p.get('last_name', '')}")


def add_business_days(start, n, holidays):
    """start moved forward by n business days (n may be 0)."""
    d, left = start, n
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            left -= 1
    return d


def next_business_day(d, holidays):
    while d.weekday() >= 5 or d in holidays:
        d += timedelta(days=1)
    return d


def sub_business_days(end, n, holidays):
    d, left = end, n
    while left > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            left -= 1
    return d


# ---------- inputs ----------

def load_config(workspace):
    path = Path(workspace) / "gtm.json"
    data = {}
    if path.exists():
        with path.open(encoding="utf-8-sig") as fh:
            data = json.load(fh)
    cfg = {
        "play": deep_merge(DEFAULT_PLAY, data.get("play", {})),
        "stop_statuses": data.get("stop_statuses", DEFAULT_STOP),
        "dnc_tags": data.get("dnc_tags", DEFAULT_DNC),
        "left_tags": data.get("left_tags", DEFAULT_LEFT),
        "personas": data.get("personas", []),
        "holidays": {d for d in (parse_day(x) for x in data.get("daily", {}).get("holidays", [])) if d},
    }
    return cfg


def load_play(path, cfg):
    path = Path(path)
    if not path.exists():
        raise ValueError(f"play file not found: {path}")
    with path.open(encoding="utf-8-sig") as fh:
        play = json.load(fh)
    missing = [key for key in ("id", "type", "sequence", "start", "channel", "daily_cap")
               if play.get(key) in (None, "")]
    if missing:
        raise ValueError("play.json is missing: " + ", ".join(missing) + ". Ask the user for them before "
                         "building the play; nothing was written.")
    share = play.get("holdout_share", 0)
    if not isinstance(share, (int, float)) or not 0 <= share <= 0.5:
        raise ValueError("holdout_share must be a number from 0 to 0.5")
    if play["type"] not in TYPES:
        raise ValueError(f"play type must be one of {', '.join(TYPES)}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", play["id"]):
        raise ValueError("play id: lowercase letters, numbers and dashes only")
    if not parse_day(play["start"]):
        raise ValueError("play start must be YYYY-MM-DD")
    if play.get("end") and not parse_day(play["end"]):
        raise ValueError("play end must be YYYY-MM-DD")
    if play.get("channel", "email") not in ("email", "call", "any"):
        raise ValueError("play channel must be email, call or any")
    settings = deep_merge(cfg["play"], {k: v for k, v in play.items()
                                        if k in ("daily_cap", "holdout_share", "per_account_cap", "recent_touch_days",
                                                 "owner", "seat_order", "max_quiet_runs",
                                                 "conversation_days")})
    for sub in ("event", "reactivation", "multithread"):
        if isinstance(play.get(sub), dict):
            settings[sub] = deep_merge(cfg["play"][sub], play[sub])
    return play, settings


def sequence_days(workspace, seq_id, default):
    path = Path(workspace) / "outreach" / "sequences.json"
    if not path.exists():
        return default, ["outreach/sequences.json not found: assumed a %d-day sequence" % default], []
    with path.open(encoding="utf-8-sig") as fh:
        data = json.load(fh)
    for seq in data.get("sequences", []):
        if seq.get("id") == seq_id:
            days = [int(s.get("day", 1)) for s in seq.get("steps", [])] or [default]
            return max(days), [], sorted(seq.get("variables", {}))
    return default, [f"sequence '{seq_id}' is not in outreach/sequences.json: assumed {default} days"], []


def load_activity(workspace, today):
    rows, corrupt = [], 0
    for r in read_csv(Path(workspace) / "log" / "activity.csv"):
        d = parse_day(r.get("timestamp"))
        if d is None:
            continue
        if d > today:
            corrupt += 1
            continue
        r["_day"] = d
        rows.append(r)
    return rows, corrupt


# ---------- the play ----------

class Funnel:
    def __init__(self, start):
        self.start = start
        self.steps = []  # (rule, removed, {reason: count})

    def step(self, rule, dropped):
        reasons = {}
        for _, why in dropped:
            reasons[why] = reasons.get(why, 0) + 1
        self.steps.append((rule, len(dropped), reasons))


def last_touch(person, activity_by_person):
    days = [r["_day"] for r in activity_by_person.get(person.get("person_id"), [])
            if r.get("direction", "out") == "out"]
    d = parse_day(person.get("last_touch_date"))
    if d:
        days.append(d)
    return max(days) if days else None


def account_scope(play, settings, accounts, people_by_acct, signals, events, activity, today, notes):
    """Return {account_id: (rank_key, info)} for accounts in this play's scope,
    plus {account_id: reason} for accounts out of scope."""
    kind = play["type"]
    scope, out = {}, {}
    tier_pts = settings["tier_points"]
    if kind == "signal":
        for aid, a in accounts.items():
            s = signals.get(aid)
            if s and s.get("playable") == "yes":
                scope[aid] = ((-(to_num(s.get("score"), 0)), aid), {"signal": s})
            else:
                out[aid] = "no playable signal" if not s else "signal not playable: " + (s.get("why_not") or "see signals")
    elif kind == "blitz":
        listed = [x for x in play.get("accounts", []) if x]
        missing = [x for x in listed if x not in accounts]
        if missing:
            notes.append("blitz names accounts not in the book: " + ", ".join(missing))
        for aid in accounts:
            if aid in listed:
                scope[aid] = ((listed.index(aid), aid), {})
            else:
                out[aid] = "not in the blitz list"
    elif kind == "event":
        for aid, a in accounts.items():
            scope[aid] = ((-tier_pts.get(a.get("tier", ""), 0), aid), {})
    elif kind == "reactivation":
        rs = settings["reactivation"]
        touches = {}
        for r in activity:
            if r.get("direction", "out") == "out":
                touches.setdefault(r.get("account_id"), set()).add(r["_day"])
        for aid, ppl in people_by_acct.items():
            for p in ppl:
                d = parse_day(p.get("last_touch_date"))
                if d:
                    touches.setdefault(aid, set()).add(d)
        for aid, a in accounts.items():
            tagged = (set(split_list(a.get("tags"))) & set(rs["account_tags"])) or a.get("strategy") == "re-engage"
            days = sorted(touches.get(aid, set()))
            if not days:
                out[aid] = "never touched: this is prospecting, not reactivation"
                continue
            gaps = [(b - a_).days for a_, b in zip(days, days[1:]) if (b - a_).days > 0]
            interval = sorted(gaps)[len(gaps) // 2] if gaps else rs["default_interval_days"]
            quiet = (today - days[-1]).days
            needed = max(rs["min_quiet_days"], rs["gap_factor"] * interval)
            if tagged or quiet >= needed:
                value = to_num(a.get("past_value"), 0)
                info = {"quiet_days": quiet, "usual_interval": interval, "last_touch": days[-1].isoformat(),
                        "why": "tagged for re-engage" if tagged else
                        f"quiet {quiet} days; usual gap {interval} days"}
                scope[aid] = ((-value, -tier_pts.get(a.get("tier", ""), 0), aid), info)
            else:
                out[aid] = f"not quiet yet: {quiet} days since last touch, needs {int(needed)}"
    elif kind == "multithread":
        engaged_out = set(settings["multithread"]["engaged_outcomes"])
        engaged = {}
        for r in activity:
            if r.get("outcome") in engaged_out:
                engaged.setdefault(r.get("account_id"), set()).add(r.get("person_id"))
        for aid, a in accounts.items():
            if aid in engaged:
                lanes = {p.get("lane") for p in people_by_acct.get(aid, []) if p.get("person_id") in engaged[aid]}
                scope[aid] = ((-len(engaged[aid]), aid), {"engaged": engaged[aid], "engaged_lanes": lanes})
            else:
                out[aid] = "nobody engaged yet"
    return scope, out


def pick_named(signal, ppl):
    """People named in the signal's seat text, and names the seat text rules out."""
    seat = norm((signal or {}).get("seat"))
    banned = set()
    for m in re.finditer(r"\bnot ([a-z][a-z'.-]+ [a-z][a-z'.-]+)", seat):
        banned.add(m.group(1))
    named = [p for p in ppl if full_name(p) and full_name(p) in seat and full_name(p) not in banned]
    return named, banned


def build(workspace, play_path, today):
    workspace = Path(workspace)
    cfg = load_config(workspace)
    play, settings = load_play(play_path, cfg)
    out_dir = workspace / "plays" / play["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    play_path = Path(play_path).resolve()
    if play_path.parent == out_dir.resolve() and play_path.name in OUTPUTS:
        raise ValueError("the play file cannot be one of this script's output files")

    people = read_csv(workspace / "book" / "people.csv")
    acct_rows = read_csv(workspace / "book" / "accounts.csv")
    if not people or not acct_rows:
        raise ValueError("book/people.csv and book/accounts.csv are needed: run account-book first")
    accounts = {a["account_id"]: a for a in acct_rows}
    people_by_acct = {}
    for p in people:
        people_by_acct.setdefault(p.get("account_id"), []).append(p)

    notes, needs = [], []
    seq_len, seq_notes, seq_vars = sequence_days(workspace, play["sequence"], settings["default_sequence_days"])
    needs.extend(seq_notes)
    activity, corrupt = load_activity(workspace, today)
    if corrupt:
        notes.append(f"{corrupt} activity row{'s' if corrupt != 1 else ''} dated after {today} "
                     "ignored as corrupt: fix the timestamp in log/activity.csv")
    act_by_person = {}
    for r in activity:
        act_by_person.setdefault(r.get("person_id"), []).append(r)

    signals = {}
    if play["type"] == "signal":
        rows = read_csv(workspace / "signals" / "scored.csv")
        if not rows:
            raise ValueError("signals/scored.csv is needed for a signal play: run signal-score first")
        signals = {r["account_id"]: r for r in rows}

    event = None
    if play["type"] == "event":
        es = settings["event"]
        rows = read_csv(workspace / es.get("file", "input/events.csv"))
        event = next((e for e in rows if e.get("event_id") == es.get("event_id")), None)
        if not event:
            raise ValueError(f"event '{es.get('event_id')}' not found in {es.get('file')}")
        if norm(event.get("status")) == "tentative":
            needs.append(f"event {event['event_id']} is tentative: nothing is proposed until it is confirmed")

    channel = play.get("channel", "email")
    gate_label = {"email": "email", "call": "call", "any": "email or call"}[channel]
    personas = set(play.get("personas") or [])
    if event and not personas:
        personas = set(split_list(event.get("personas")))
    per_cap = settings["per_account_cap"]
    if play["type"] == "event":
        per_cap = play.get("per_account_cap", settings["event"]["invites_per_account"])
    if play["type"] == "multithread":
        per_cap = play.get("per_account_cap", settings["multithread"]["per_account_cap"])

    holidays = cfg["holidays"]
    start = next_business_day(max(parse_day(play["start"]), today), holidays)
    last_start = parse_day(play.get("end")) if play.get("end") else None
    if event:
        ev_day = parse_day(event.get("date"))
        if not ev_day:
            raise ValueError("event date must be YYYY-MM-DD")
        finish = sub_business_days(ev_day, settings["event"]["finish_days_before"], holidays)
        cutoff = sub_business_days(finish, seq_len - 1, holidays)
        last_start = min(last_start, cutoff) if last_start else cutoff
    if last_start and last_start < start:
        needs.append(f"no start date fits: the last possible start ({last_start}) is before {start}")

    # previous run and overrides
    prev = {r["person_id"]: r for r in read_csv(out_dir / "enroll.csv")}

    def approved_before(pid):
        r = prev.get(pid, {})
        return norm(r.get("approved")) == "yes" and not (r.get("drop_reason") or "").strip()
    # kept: approved earlier and not blocked since. running: kept and already started.
    kept = {pid for pid in prev if approved_before(pid)}
    running = {pid for pid in kept if parse_day(prev[pid].get("sequence_start"))
               and parse_day(prev[pid].get("sequence_start")) <= today}
    state_path = out_dir / "state.json"
    state = {"runs": []}
    if state_path.exists():
        with state_path.open(encoding="utf-8-sig") as fh:
            state = json.load(fh)
    last_script_vars = state.get("script_vars", {})
    overrides = read_csv(out_dir / "overrides.csv")
    removed = {o["person_id"]: o.get("reason", "") for o in overrides if norm(o.get("action")) == "remove"}
    added = {o["person_id"]: o.get("reason", "") for o in overrides if norm(o.get("action")) == "add"}
    stopping = (set(settings["stop_outcomes"]) | set(settings["email_stop_outcomes"])
                | set(settings["conversation_outcomes"]))
    other_live = {}
    for other in sorted((workspace / "plays").glob("*/enroll.csv")):
        if other.parent.name == play["id"]:
            continue
        other_seq = ""
        other_play = other.parent / "play.json"
        if other_play.exists():
            try:
                with other_play.open(encoding="utf-8-sig") as fh:
                    other_seq = json.load(fh).get("sequence", "")
            except ValueError:
                other_seq = ""
        other_len = sequence_days(workspace, other_seq, settings["default_sequence_days"])[0]
        for r in read_csv(other):
            if norm(r.get("approved")) != "yes" or r.get("drop_reason"):
                continue
            began = parse_day(r.get("sequence_start"))
            if began:
                # A finished sequence no longer holds the person.
                if add_business_days(began, max(other_len - 1, 0), holidays) < today:
                    continue
                # Neither does one a stop outcome ended (the rules below still apply to that outcome).
                if any(a.get("outcome") in stopping and a["_day"] >= began
                       for a in act_by_person.get(r["person_id"], [])):
                    continue
            other_live[r["person_id"]] = other.parent.name

    scope, out_of_scope = account_scope(play, settings, accounts, people_by_acct, signals, event,
                                        activity, today, notes)
    # A sequence already under way keeps running when its account leaves the play's scope
    # (a signal expires, an account stops being quiet). Only that person stays in.
    running_only = set()
    for p in people:
        aid = p.get("account_id")
        if p["person_id"] in running and aid in accounts and aid not in scope:
            scope[aid] = ((10 ** 6 - 1, aid), {"running": True})
            running_only.add(aid)

    funnel = Funnel(len(people))
    alive = list(people)
    dropped = {}    # person_id -> reason (only in-scope people are written to enroll.csv)
    suggestions = []

    def apply(rule, test, record=True):
        nonlocal alive
        keep, gone = [], []
        for p in alive:
            why = test(p)
            if why:
                gone.append((p, why))
                if record:
                    dropped[p["person_id"]] = why
            else:
                keep.append(p)
        funnel.step(rule, gone)
        alive = keep

    stop, dnc, left_tags = set(cfg["stop_statuses"]), set(cfg["dnc_tags"]), set(cfg["left_tags"])

    stop_outcomes = set(settings["stop_outcomes"])
    if channel == "email":
        stop_outcomes |= set(settings["email_stop_outcomes"])
    talk_outcomes = set(settings["conversation_outcomes"])
    talk_days = settings["conversation_days"]

    def hard_stop(p):
        if p.get("status") in stop:
            return f"status {p.get('status')}"
        tags = set(split_list(p.get("tags")))
        if tags & dnc:
            return "opted out (" + ", ".join(sorted(tags & dnc)) + ")"
        if tags & left_tags:
            return "may have left (" + ", ".join(sorted(tags & left_tags)) + ")"
        hits = sorted((a["_day"], a.get("outcome")) for a in act_by_person.get(p["person_id"], [])
                      if a.get("outcome") in stop_outcomes)
        if hits:
            return f"log outcome {hits[-1][1]} on {hits[-1][0].isoformat()}"
        return ""

    def in_conversation(p):
        hits = sorted(a["_day"] for a in act_by_person.get(p["person_id"], [])
                      if a.get("outcome") in talk_outcomes and (today - a["_day"]).days <= talk_days)
        if hits:
            return f"in a live conversation since {hits[-1].isoformat()}: reply by hand"
        return ""

    def account_rule(p):
        a = accounts[p["account_id"]]
        blocked = account_block(a)
        if blocked:
            return blocked
        if norm(a.get("owner")) not in ("", norm(settings["owner"])):
            return f"owned by {a.get('owner')}"
        return ""

    def in_sequence(p):
        pid = p["person_id"]
        if pid in kept and (not p.get("sequence") or p.get("sequence") == play["sequence"]):
            return ""  # approved in this play earlier
        if p.get("sequence"):
            suggestions.append((p, p["sequence"]))
            return f"already in sequence {p['sequence']}: reply in that thread instead"
        if pid in other_live:
            suggestions.append((p, other_live[pid]))
            return f"approved in play {other_live[pid]}: one live play per person"
        return ""

    def gate(p):
        if channel == "email":
            ok, why = p.get("send_ok"), p.get("send_block_reason")
        elif channel == "call":
            ok, why = p.get("call_ok"), p.get("call_block_reason")
        else:
            ok = "yes" if "yes" in (p.get("send_ok"), p.get("call_ok")) else "no"
            parts = []
            for chunk in (p.get("send_block_reason"), p.get("call_block_reason")):
                for x in split_list(str(chunk or "").replace("; ", ";")):
                    if x not in parts:
                        parts.append(x)
            why = "; ".join(parts)
        if ok == "yes":
            return ""
        # Anyone still here who has a sequence is running in this play; that reason does not count.
        why = re.sub(r"(^|; )already in (a )?sequence[^;]*", "", why or "").strip("; ")
        return f"{gate_label} gate: {why}" if why else ""

    # 1. account in scope
    def in_scope(p):
        aid = p.get("account_id")
        if aid in scope and (aid not in running_only or p["person_id"] in running):
            return ""
        return "account: " + out_of_scope.get(aid, "not in the book")
    apply("Account is in this play's scope", in_scope, record=False)
    # 2. account strategy
    apply("Account strategy allows outbound", lambda p: account_block(accounts[p["account_id"]]))
    # 3. owner
    owner = norm(settings["owner"])
    apply("Account is yours to work",
          lambda p: f"owned by {accounts[p['account_id']].get('owner')}"
          if norm(accounts[p["account_id"]].get("owner")) not in ("", owner) else "")
    # 4. hard stops
    apply("No stop status, opt-out, left tag or stop outcome in the log", hard_stop)
    # 4b. open conversations are handled by a person
    apply(f"Not in a conversation from the last {talk_days} days", in_conversation)
    # 5. live sequences
    apply("Not already in a live sequence", in_sequence)
    # 6. channel gate
    apply(f"Passes the {gate_label} gate from the book", gate)
    # 7. persona
    if personas:
        apply("Persona fits the play", lambda p: "" if p.get("persona") in personas else
              f"persona {p.get('persona') or 'none'} is not in this play")
    else:
        apply("Is a buyer (has a persona)", lambda p: "" if p.get("persona") else "no persona: not a buyer")
    # 7b. event metro
    if event:
        codes = set(split_list(event.get("area_codes")))

        def metro(p):
            if p["person_id"] in running:
                return ""
            digits = re.sub(r"\D", "", p.get("phone") or "")
            area = digits[1:4] if digits.startswith("1") and len(digits) == 11 else digits[:3]
            return "" if area and area in codes else f"not near {event.get('city') or 'the event'}"
        apply("Lives near the event", metro)
    # 7c. multithread: only new lanes
    if play["type"] == "multithread":
        def new_lane(p):
            info = scope[p["account_id"]][1]
            if p["person_id"] in running or info.get("running"):
                return ""
            if p.get("person_id") in info["engaged"] or p.get("lane") in info["engaged_lanes"]:
                return "lane already engaged"
            return ""
        apply("Adds a new lane at an engaged account", new_lane)
    # 8. recently touched
    recent = settings["recent_touch_days"]
    if play["type"] == "reactivation":
        recent = settings["reactivation"].get("recent_touch_days", recent)

    def recent_touch(p):
        if p["person_id"] in running:
            return ""  # its own touches come from this play
        d = last_touch(p, act_by_person)
        if d and (today - d).days < recent:
            return f"touched {d.isoformat()}, within {recent} days"
        return ""
    apply(f"Not touched in the last {recent} days", recent_touch)
    # 9. your removals
    apply("Not removed by you", lambda p: f"removed by you: {removed[p['person_id']]}"
          if p["person_id"] in removed else "")
    # 9b. holdout: a stable share of accounts stays untouched so the play can be measured.
    # It is applied after seat choice (step 10), so the holdout side counts the same unit as
    # the worked side: the seat that would have been touched, not everyone eligible there.
    holdout = float(settings.get("holdout_share") or 0)

    def held_account(aid):
        if holdout <= 0:
            return False
        return int(hashlib.sha256(f"{play['id']}:{aid}".encode()).hexdigest(), 16) / 16 ** 64 < holdout

    # your additions come back if the hard rules allow
    added_now = []
    for pid, why in sorted(added.items()):
        p = next((x for x in people if x["person_id"] == pid), None)
        if p is None:
            needs.append(f"override adds {pid}, who is not in the book")
            continue
        if held_account(p.get("account_id", "")) and pid not in kept and pid not in running:
            needs.append(f"override adds {pid}, but {pid} is at a held-out account: they stay out so the "
                         "comparison holds. Set holdout_share to 0 to work every account.")
            continue
        if p in alive:
            alive[alive.index(p)] = dict(p, _added=why)
            continue
        hard = (account_rule(p) or hard_stop(p) or in_conversation(p) or gate(p)
                or (in_sequence(p) if p.get("sequence") or pid in other_live else ""))
        if hard:
            needs.append(f"override adds {pid} but a hard rule blocks them: {hard}")
            continue
        if p.get("account_id") not in scope:
            scope[p["account_id"]] = ((10 ** 6, p["account_id"]), {})
        p = dict(p, _added=why)
        alive.append(p)
        dropped.pop(pid, None)
        added_now.append(p)
    if added_now:
        add_reasons = {}
        for p in added_now:
            key = f"added: {p['_added']}"
            add_reasons[key] = add_reasons.get(key, 0) + 1
        funnel.steps.append(("Added back by you (overrides.csv)", -len(added_now), add_reasons))

    # 10. seat choice and per-account cap
    seat_order = settings["seat_order"]
    chosen, seat_of, seat_drops = [], {}, []
    for aid in sorted({p["account_id"] for p in alive}, key=lambda a: scope[a][0]):
        group = [p for p in alive if p["account_id"] == aid]
        info = scope[aid][1]
        order = list(seat_order)
        if play["type"] == "signal" and "signal" in info:
            sig = info.get("signal", {})
            order = settings["signal_seat_roles"].get(sig.get("top_type"), seat_order)
            named, banned = pick_named(sig, people_by_acct.get(aid, []))
            group = [p for p in group if full_name(p) not in banned]
            if "named" in order:
                named_ids = {p["person_id"] for p in named}
                info["_named_ids"] = sorted(named_ids)
                in_group = [p for p in group if p["person_id"] in named_ids]
                if in_group:
                    # People approved earlier keep their seats next to the named leader.
                    group = in_group + [p for p in group if p["person_id"] in kept and p not in in_group]
                else:
                    info["_named_missing"] = True
                    needs.append(f"{accounts[aid].get('name')}: the named person in the signal is not workable "
                                 f"in the book ({sig.get('seat')}). The next seat gets a plain first touch: "
                                 "trigger_fact is left blank because the fact is about someone else. Write a "
                                 "plain first line in it, or add the named person to the book and rerun.")
                order = [o for o in order if o != "named"]

        def seat_key(p):
            if p["person_id"] in kept:
                return (-2, p["person_id"])  # approved earlier: keeps the seat
            if p.get("_added"):
                return (-1, p["person_id"])
            role = p.get("role") or ""
            return (order.index(role) if role in order else len(order), p["person_id"])
        group.sort(key=seat_key)
        taken = 0
        for p in group:
            # People approved earlier keep their seat and count toward the cap. People you
            # added come on top of the cap; they do not take a seat from the play.
            fits = p["person_id"] in kept or bool(p.get("_added")) or taken < per_cap
            if fits and (p["person_id"] in kept or not p.get("_added")):
                taken += 1
            if fits:
                chosen.append(p)
                if p["person_id"] in kept and prev[p["person_id"]].get("seat"):
                    seat_of[p["person_id"]] = prev[p["person_id"]]["seat"]
                elif p.get("_added"):
                    seat_of[p["person_id"]] = "added by you: " + p["_added"]
                elif play["type"] == "signal" and info.get("_named_missing"):
                    seat_of[p["person_id"]] = (f"{p.get('role') or 'buyer'} (the named leader is not in the book: "
                                               "plain first touch)")
                elif play["type"] == "signal" and "signal" in info:
                    seat_of[p["person_id"]] = f"{p.get('role') or 'buyer'} (signal seat: {info['signal'].get('seat')})"
                else:
                    seat_of[p["person_id"]] = p.get("role") or "buyer"
            else:
                seat_drops.append((p, f"account cap: {per_cap} per account"))
        for p in [x for x in alive if x["account_id"] == aid and x not in group and x not in chosen]:
            seat_drops.append((p, "not the seat this signal points to"))
    for p, why in seat_drops:
        dropped[p["person_id"]] = why
    funnel.step(f"Seat choice, at most {per_cap} per account", seat_drops)
    if holdout > 0:
        held = [(p, "holdout: kept untouched so the play can be measured") for p in chosen
                if held_account(p["account_id"]) and p["person_id"] not in kept and p["person_id"] not in running]
        held_ids = {p["person_id"] for p, _ in held}
        for p, why in held:
            dropped[p["person_id"]] = why
        chosen = [p for p in chosen if p["person_id"] not in held_ids]
        funnel.step(f"Not in the holdout ({holdout:.0%} of accounts kept untouched for comparison)", held)

    # 11. start dates: approved rows keep theirs, then round-robin by account under the daily cap
    tentative = event is not None and norm(event.get("status")) == "tentative"
    load, used_acct_day = {}, set()
    plan = {}
    for p in chosen:
        old = prev.get(p["person_id"], {})
        d = parse_day(old.get("sequence_start"))
        if p["person_id"] in kept and d:
            plan[p["person_id"]] = d
            load[d] = load.get(d, 0) + 1
            used_acct_day.add((p["account_id"], d))
    queues = {}
    for p in chosen:
        if p["person_id"] not in plan:
            queues.setdefault(p["account_id"], []).append(p)
    acct_order = sorted(queues, key=lambda a: scope[a][0])
    cap_drops = []
    day = start
    pending = [list(queues[a]) for a in acct_order]
    guard = 0
    while any(pending) and not tentative:
        guard += 1
        if guard > 2000 or (last_start and day > last_start):
            break
        for q in pending:
            if not q or load.get(day, 0) >= settings["daily_cap"]:
                continue
            p = q[0]
            if (p["account_id"], day) in used_acct_day:
                continue
            plan[p["person_id"]] = day
            load[day] = load.get(day, 0) + 1
            used_acct_day.add((p["account_id"], day))
            q.pop(0)
        day = add_business_days(day, 1, holidays)
    for q in pending:
        for p in q:
            cap_drops.append((p, "event is tentative: wait" if tentative else
                              f"no start date left before {last_start}" if last_start else "over capacity"))
    for p, why in cap_drops:
        dropped[p["person_id"]] = why
    funnel.step(f"Fits the calendar ({settings['daily_cap']} a day, one per account a day)", cap_drops)

    # rows
    rows, intent_noted = [], set()
    script_vars = {}
    ranked = sorted((p for p in chosen if p["person_id"] in plan),
                    key=lambda p: (plan[p["person_id"]], scope[p["account_id"]][0], p["person_id"]))
    for i, p in enumerate(ranked, 1):
        pid = p["person_id"]
        a = accounts[p["account_id"]]
        info = scope[p["account_id"]][1]
        old = prev.get(pid, {})
        variables = {"first_name": p.get("first_name", ""), "company": a.get("name", "")}
        if play["type"] == "signal" and "signal" in info:
            sig_row = info["signal"]
            check = (sig_row.get("check") or "").strip()
            if pid in info.get("_named_ids", []):
                # The seat is the leader the signal names: the line is written to them.
                fact = you_fact(a.get("name", ""), sig_row.get("why_now", ""),
                                p.get("first_name", ""), p.get("last_name", ""))
            else:
                fact = trigger_fact(a.get("name", ""), sig_row.get("why_now", ""))
            if sig_row.get("top_type") == "topic_intent":
                # Research-interest data is timing only. It is never quoted, so no trigger fact.
                variables["trigger_fact"] = ""
                if pid not in intent_noted:
                    intent_noted.add(pid)
                    needs.append(f"{p.get('first_name')} {p.get('last_name')} ({pid}): the only signal is "
                                 "research interest. Use it for timing only and never mention it. Put a sourced, "
                                 "dated fact in trigger_fact only if you find one; otherwise the step is held.")
            elif info.get("_named_missing") and seat_of.get(pid, "").find("plain first touch") >= 0:
                # The fact is about the named leader, who is not this person: no trigger fact.
                variables["trigger_fact"] = ""
                variables["source_url"] = sig_row.get("source_url", "")
                variables["source_date"] = sig_row.get("event_date", "")
            elif check:
                # signal-score could not confirm the source is about this account: never quote it yet.
                variables["trigger_fact"] = ""
                variables["trigger_fact_to_confirm"] = fact
                variables["source_url"] = sig_row.get("source_url", "")
                variables["source_date"] = sig_row.get("event_date", "")
                needs.append(f"needs human: confirm the fact for {p.get('first_name')} {p.get('last_name')} ({pid}). "
                             f"{check}. trigger_fact is blank until you open the source and copy "
                             "trigger_fact_to_confirm into trigger_fact.")
            else:
                variables["trigger_fact"] = fact
                variables["source_url"] = sig_row.get("source_url", "")
                variables["source_date"] = sig_row.get("event_date", "")
        if event:
            variables.update({"event_name": event.get("name", ""), "event_date": event.get("date", ""),
                              "event_city": event.get("city", "")})
        if play["type"] == "reactivation" and "last_touch" in info:
            variables.update({"last_touch": info.get("last_touch", ""), "quiet_days": str(info.get("quiet_days", ""))})
        live_word = conversation_word(p.get("_added", ""), settings["override_conversation_words"])
        if live_word:
            # You added them for a reason that sounds like they are already talking to you
            # (a demo request, a reply, a meeting). A cold first line would ignore that.
            variables["trigger_fact"] = ""
            variables.pop("trigger_fact_to_confirm", None)
            needs.append(f"{p.get('first_name')} {p.get('last_name')} ({pid}): reply by hand first: the override "
                         f"reason suggests a live conversation (\"{p.get('_added')}\", matched \"{live_word}\"). "
                         "trigger_fact is left blank. Answer them yourself before any sequence step, then "
                         "decide if this play still fits.")
        for v in seq_vars:
            variables.setdefault(v, "")
        script_vars[pid] = dict(variables)
        # Keep what you typed: a value in enroll.csv that differs from what the script wrote last time
        # is yours. A sequence already running keeps all of its variables.
        try:
            old_vars = json.loads(old.get("variables") or "{}")
        except ValueError:
            old_vars = {}
        last = last_script_vars.get(pid, {})
        for k, v in old_vars.items():
            if pid in running and (v != "" or k not in variables):
                variables[k] = v
            elif v != "" and v != last.get(k, ""):
                variables[k] = v
        approved = ""
        if norm(old.get("approved")) in ("yes", "no") and not (old.get("drop_reason") or "").strip():
            approved = norm(old.get("approved"))
        elif norm(old.get("approved")) == "yes":
            needs.append(f"{p.get('first_name')} {p.get('last_name')} ({pid}) was blocked and now qualifies "
                         "again: approve the row again if you still want them in")
        rows.append({
            "play_id": play["id"], "person_id": pid, "account_id": p["account_id"],
            "seat": seat_of.get(pid, ""), "sequence": play["sequence"],
            "sequence_start": plan[pid].isoformat(),
            "variables": json.dumps(variables, sort_keys=True), "rank": str(i),
            "approved": approved, "drop_reason": "",
        })
    blanks = {}
    for r in rows:
        for k, v in json.loads(r["variables"]).items():
            if v == "" and k in seq_vars:
                blanks.setdefault(k, []).append(r["person_id"])
    for k, ids in sorted(blanks.items()):
        needs.append(f"variable `{k}` is blank for {', '.join(ids)}: fill it in enroll.csv before the first step, "
                     "or the step is held for you")
    quoting = sorted(r["person_id"] for r in rows
                     if json.loads(r["variables"]).get("trigger_fact") and json.loads(r["variables"]).get("source_url"))
    if quoting:
        needs.append(f"open each source link before the first touch ({', '.join(quoting)} quote a dated fact). "
                     "If the page is gone or says something else, clear trigger_fact.")
    in_scope_ids = {p["person_id"] for p in people if p.get("account_id") in scope}
    for pid in sorted(dropped):
        if pid not in in_scope_ids:
            continue
        p = next(x for x in people if x["person_id"] == pid)
        old = prev.get(pid, {})
        why = dropped[pid]
        approved = norm(old.get("approved")) if norm(old.get("approved")) == "no" else ""
        if norm(old.get("approved")) == "yes":
            # The flag stays, with approved kept as yes, until you clear approved yourself.
            # daily-plan never works a row that has a drop_reason.
            why = f"was approved, now blocked: {why}"
            approved = "yes"
            needs.append(f"{p.get('first_name')} {p.get('last_name')} ({pid}) was approved but is now blocked: "
                         f"{dropped[pid]}. Clear `approved` once you have seen this.")
        rows.append({"play_id": play["id"], "person_id": pid, "account_id": p.get("account_id", ""),
                     "seat": "", "sequence": play["sequence"], "sequence_start": "", "variables": "",
                     "rank": "", "approved": approved, "drop_reason": why})

    # progress state
    new_people = [r for r in rows if r["rank"] and (r["person_id"] not in prev or prev[r["person_id"]].get("drop_reason"))]
    state["script_vars"] = {pid: script_vars[pid] for pid in sorted(script_vars)}
    runs = [r for r in state.get("runs", []) if r.get("date") != today.isoformat()]
    runs.append({"date": today.isoformat(), "proposed": len(ranked), "new": len(new_people)})
    runs.sort(key=lambda r: r["date"])
    state["runs"] = runs
    k = settings["max_quiet_runs"]
    stalled = len(runs) >= k and all(r["new"] == 0 for r in runs[-k:])

    # override reasons that repeat
    reasons = {}
    for o in overrides:
        key = norm(o.get("reason"))
        if key:
            reasons.setdefault((norm(o.get("action")), key), []).append(o["person_id"])
    rule_ideas = [(act, why, ids) for (act, why), ids in sorted(reasons.items()) if len(ids) >= 2]

    write_csv(out_dir / "enroll.csv", rows, ENROLL_COLS)
    with state_path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    write_funnel(out_dir / "funnel.md", play, funnel, len(ranked))
    write_report(out_dir / "report.md", play, today, ranked, plan, rows, needs, notes, suggestions,
                 rule_ideas, stalled, k, last_start, seq_len)
    return {"play": play["id"], "proposed": len(ranked), "new": len(new_people),
            "dropped_in_scope": sum(1 for r in rows if r["drop_reason"]),
            "needs_you": len(needs), "stalled": stalled, "out_dir": str(out_dir)}


# ---------- writing ----------

def write_funnel(path, play, funnel, final):
    lines = [f"# Eligibility funnel: {play['id']}", "",
             f"Play type: {play['type']}. Every drop is counted with its reason.", "",
             "| Step | Rule | Removed | Left |", "|---|---|---|---|",
             f"| 0 | Everyone in the book | | {funnel.start} |"]
    left = funnel.start
    for i, (rule, removed, _) in enumerate(funnel.steps, 1):
        left -= removed
        shown = f"+{-removed} added" if removed < 0 else str(removed)
        lines.append(f"| {i} | {rule} | {shown} | {left} |")
    removed_total = sum(removed for _, removed, _ in funnel.steps)
    lines += ["", f"Proposed: {final}."]
    if funnel.start - removed_total == final:
        lines.append(f"Check: {funnel.start} in the book minus {removed_total} removed (adds count as negative) "
                     f"equals {final} proposed. The counts add up.")
    else:
        lines.append(f"Check FAILED: {funnel.start} minus {removed_total} is {funnel.start - removed_total}, "
                     f"not {final}. The funnel lost track of someone; report this before approving rows.")
    lines += ["", "## Reasons", ""]
    for i, (rule, removed, reasons) in enumerate(funnel.steps, 1):
        if not removed:
            continue
        lines.append(f"**{i}. {rule}**")
        for why, n in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):  # noqa: B007
            lines.append(f"- {n}: {why}")
        lines.append("")
    Path(path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_report(path, play, today, ranked, plan, rows, needs, notes, suggestions, rule_ideas,
                 stalled, k, last_start, seq_len):
    lines = [f"# Play report: {play['id']} ({today.isoformat()})", ""]
    lines += ["## Needs you", ""]
    items = ["Open `enroll.csv`, read each proposed row and write `yes` (or `no`) in `approved`. "
             "Only approved rows are worked."]
    items += needs
    for p, where in suggestions:
        items.append(f"{p.get('first_name')} {p.get('last_name')} ({p['person_id']}) is already in {where}: "
                     "reply in that thread instead of a new sequence.")
    if stalled:
        items.append(f"This play found nobody new in its last {k} runs. Retire it or change its rules.")
    lines += [f"- {x}" for x in items] + [""]
    lines += ["## Proposed", ""]
    if ranked:
        lines += ["| Rank | Person | Account | Seat | Starts |", "|---|---|---|---|---|"]
        for r in rows:
            if r["rank"]:
                lines.append(f"| {r['rank']} | {r['person_id']} | {r['account_id']} | {r['seat']} | {r['sequence_start']} |")
    else:
        lines.append("Nobody this run. See `funnel.md` for where people dropped.")
    lines += ["", f"Sequence `{play['sequence']}` runs {seq_len} business days."]
    if last_start:
        lines.append(f"Last possible start: {last_start.isoformat()}.")
    if play["type"] == "reactivation":
        lines += ["", "Reactivation rules: the first touch names the gap and does not pitch. Any reply, "
                  "including an out-of-office, pauses the sequence. A complaint stops it."]
    if rule_ideas:
        lines += ["", "## Rule ideas from your overrides", ""]
        for act, why, ids in rule_ideas:
            lines.append(f"- You {act}d {len(ids)} people for the same reason (\"{why}\"): "
                         f"{', '.join(sorted(ids))}. Consider making it a rule in play.json.")
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    lines += ["", "Nothing was sent, enrolled or written to any CRM or sequencer."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill one play from the book. Writes files only.")
    ap.add_argument("--workspace", default="gtm", help="GTM workspace folder (default ./gtm)")
    ap.add_argument("--play", required=True, help="path to play.json")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    today = parse_day(args.today)
    if not today:
        ap.error("--today must be YYYY-MM-DD")
    try:
        res = build(args.workspace, args.play, today)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Play {res['play']}: {res['proposed']} proposed ({res['new']} new), "
          f"{res['dropped_in_scope']} dropped at in-scope accounts, {res['needs_you']} item(s) need you.")
    if res["stalled"]:
        print("This play found nobody new in its recent runs. Retire it or change its rules.")
    print(f"Wrote enroll.csv, funnel.md, report.md and state.json to {res['out_dir']}")
    print("Nothing was sent or enrolled. Approve rows in enroll.csv yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
