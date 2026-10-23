#!/usr/bin/env python3
"""Funnel review for an aym-gtm workspace.

Reads the activity log (log/activity.csv), and when present the book
(book/people.csv, book/accounts.csv), approved play enrollments
(plays/*/enroll.csv), funnel/tests.json, funnel/targets.json and
funnel/changes.csv. Writes funnel/report-<today>.md and
funnel/metrics-<today>.csv.

It compares the current period with the prior period of the same length,
gives every rate its sample size and a 95% interval, refuses to rate tiny
samples, splits the change in meetings into volume, rate and mix, reads
pre-registered opener and angle tests, works the quota backwards, and ends
with at most three actions or "Nothing needs to change."

Read only: no network, nothing sent, no system changed. It never writes over
an input file.
"""
import argparse
import csv
import datetime as dt
import glob
import hashlib
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

DEFAULTS = {
    "segment_by": "segment",
    "min_n_rate": 20,
    "anecdote_n": 5,
    "z": 1.96,
    "bounce_bands": [[0.02, "healthy"], [0.05, "watch"], [1.0, "stop"]],
    "min_connects_per_arm": 20,
    "min_first_touches_per_angle": 30,
    "minutes_per_touch": {"email": 3, "call": 2, "linkedin": 4},
    "logging_gap_share": 0.1,
    "benchmarks": {},
    "benchmark_alarm_factor": 10,
    # Meetings often land days or weeks after the first touch (Oct 22 review).
    "lag_lookback_days": 30,
    "cohort_maturation_days": 21,
    "cohort_weeks": 8,
}

CHANNELS = {"email", "call", "linkedin", "meeting"}
TOUCH_CHANNELS = {"email", "call", "linkedin"}
DIRECTIONS = {"out", "in"}
OUTCOMES = {"sent", "connected", "no_answer", "voicemail", "bad_number", "gatekeeper", "replied",
            "interested", "not_now", "not_interested", "booked", "bounced", "opt_out", "wrong_person", "left"}
# A connect is a call the prospect answered. bad_number, gatekeeper, no_answer and voicemail are not.
CONNECT = {"connected", "interested", "not_now", "not_interested", "booked", "wrong_person"}
# A conversation is a connect with a real exchange about the problem.
CONVERSATION = {"interested", "not_now", "not_interested", "booked"}
# An email reply or engagement.
ENGAGED = {"replied", "interested", "not_now", "not_interested", "booked"}

SEGMENT_KEYS = ("segment", "persona", "play", "industry", "tier")


# ---------------------------------------------------------------- reading

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def read_json(path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def parse_number(text):
    text = (text or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_ts(text, today):
    """Return (local date, problem). The date is read in the timestamp's own offset."""
    day, _, problem = parse_moment(text, today)
    return day, problem


def parse_moment(text, today):
    """Return (local date, ordering key in seconds, problem).

    The ordering key lets two rows be put in time order: an offset timestamp uses its real moment,
    a timestamp without an offset is read as UTC, and a date alone counts as the start of that day."""
    text = (text or "").strip()
    if not text:
        return None, None, "blank timestamp"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    utc = dt.timezone.utc
    try:
        stamp = dt.datetime.fromisoformat(text)
        day = stamp.date()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=utc)
        key = stamp.timestamp()
    except ValueError:
        try:
            day = dt.date.fromisoformat(text)
        except ValueError:
            return None, None, "unreadable timestamp"
        key = dt.datetime(day.year, day.month, day.day, tzinfo=utc).timestamp()
    if day > today:
        return None, None, "timestamp after today (treated as blank)"
    return day, key, None


def load_config(workspace):
    cfg = {"funnel": json.loads(json.dumps(DEFAULTS)), "segments": []}
    path = workspace / "gtm.json"
    if path.exists():
        data = read_json(path)
        section = data.get("funnel", {})
        for key, value in section.items():
            if isinstance(value, dict) and isinstance(cfg["funnel"].get(key), dict):
                cfg["funnel"][key] = dict(cfg["funnel"][key], **value)
            else:
                cfg["funnel"][key] = value
        cfg["segments"] = data.get("segments", [])
    if cfg["funnel"]["segment_by"] not in SEGMENT_KEYS:
        raise ValueError("funnel.segment_by must be one of: " + ", ".join(SEGMENT_KEYS))
    return cfg


# ---------------------------------------------------------------- statistics

def wilson(k, n, z):
    """95% Wilson interval. Zero events uses the rule of three: [0, 3/n]."""
    if n <= 0:
        return None, None
    if k < 0 or k > n:
        raise ValueError("Wilson interval needs 0 <= events <= base, got {} of {}".format(k, n))
    if k == 0:
        return 0.0, min(1.0, 3.0 / n)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate_cell(k, n, cfg):
    f = cfg["funnel"]
    cell = {"k": k, "n": n, "rate": None, "low": None, "high": None}
    if k > n:
        cell["label"] = "invalid: {} events for a base of {}".format(k, n)
    elif n == 0:
        cell["label"] = "no data"
    elif n < f["anecdote_n"]:
        cell["label"] = "anecdote, not a rate"
    elif n < f["min_n_rate"]:
        cell["label"] = "too few to rate"
    else:
        cell["label"] = "measured"
        cell["rate"] = k / n
        cell["low"], cell["high"] = wilson(k, n, f["z"])
    return cell


def base_alarms(cur, seg_table, cfg):
    """Rates far above a known benchmark usually mean the wrong denominator, not a great result."""
    f = cfg["funnel"]
    bench = f.get("benchmarks") or {}
    factor = f.get("benchmark_alarm_factor", 10)
    cells = [("overall", key, cur.get(key)) for key in sorted(bench)]
    for seg in seg_table:
        cells += [(seg["segment"], "meeting_rate", seg["meeting"]), (seg["segment"], "reply_rate", seg["reply"])]
    out = []
    for where, key, cell in cells:
        b = bench.get(key)
        if not cell or cell.get("rate") is None or not isinstance(b, (int, float)) or b <= 0:
            continue
        if cell["rate"] >= factor * b:
            out.append("{} {} is {} ({} of {}), {} or more times the benchmark of {}. That usually means the "
                       "wrong base: check who is in the denominator before trusting it.".format(
                           where, key.replace("_", " "), pct(cell["rate"]), cell["k"], cell["n"], factor, pct(b)))
    return out


def pct(x):
    return "{:.1f}%".format(x * 100)


def show(cell):
    if cell["label"] == "measured":
        return "{} ({} of {}; 95% range {} to {})".format(
            pct(cell["rate"]), cell["k"], cell["n"], pct(cell["low"]), pct(cell["high"]))
    if cell["label"] == "no data":
        return "no data"
    return "{} of {} ({})".format(cell["k"], cell["n"], cell["label"])


def clear_difference(a, b):
    """True only when both are measured and the intervals do not overlap."""
    if a["label"] != "measured" or b["label"] != "measured":
        return False
    return a["high"] < b["low"] or b["high"] < a["low"]


def assign_arm(test_id, person_id, arms):
    """Stable assignment: the same person always lands in the same arm."""
    digest = hashlib.sha256("{}:{}".format(test_id, person_id).encode("utf-8")).hexdigest()
    return arms[int(digest, 16) % len(arms)]


def band(rate, bands):
    for limit, name in bands:
        if rate <= limit:
            return name
    return bands[-1][1]


# ---------------------------------------------------------------- data model

class Data:
    def __init__(self, workspace, today, cfg):
        self.ws = workspace
        self.today = today
        self.cfg = cfg
        self.inputs = []
        self.excluded = []      # (row number, reason)
        self.discipline = {"missing person_id": 0, "email touch missing angle": 0,
                           "sequence row missing step": 0}
        self.people = {}
        self.accounts = {}
        self.play_of = {}
        self.groups = {}        # play_id -> {"treated": set, "holdout": set} from play-build's enroll.csv
        self.rows = []
        self._load()

    def _note_input(self, path):
        if path.exists():
            self.inputs.append(path)
            return True
        return False

    def _load(self):
        log = self.ws / "log" / "activity.csv"
        if not log.exists():
            raise ValueError("no activity log at {}".format(log))
        self.inputs.append(log)
        if self._note_input(self.ws / "book" / "people.csv"):
            for r in read_csv(self.ws / "book" / "people.csv"):
                if r.get("person_id"):
                    self.people[r["person_id"]] = r
        if self._note_input(self.ws / "book" / "accounts.csv"):
            for r in read_csv(self.ws / "book" / "accounts.csv"):
                if r.get("account_id"):
                    self.accounts[r["account_id"]] = r
        # A person's touches belong to the play they are approved in. An approved row that
        # play-build later blocked (drop_reason set) still owns touches made before the block,
        # but a live approved row in another play wins.
        blocked = []
        for path in sorted(glob.glob(str(self.ws / "plays" / "*" / "enroll.csv"))):
            self.inputs.append(Path(path))
            for r in read_csv(path):
                pid, play = r.get("person_id", ""), r.get("play_id", "")
                reason = (r.get("drop_reason") or "").strip().lower()
                if pid and reason.startswith("holdout"):
                    self.groups.setdefault(play, {"treated": set(), "holdout": set()})["holdout"].add(pid)
                elif pid and not reason and r.get("approved", "").strip().lower() == "yes":
                    self.groups.setdefault(play, {"treated": set(), "holdout": set()})["treated"].add(pid)
                if r.get("approved", "").strip().lower() == "yes" and r.get("person_id"):
                    if (r.get("drop_reason") or "").strip():
                        blocked.append(r)
                    else:
                        self.play_of.setdefault(r["person_id"], r.get("play_id", ""))
        for r in blocked:
            self.play_of.setdefault(r["person_id"], r.get("play_id", ""))
        for i, r in enumerate(read_csv(log), start=2):
            day, when, problem = parse_moment(r.get("timestamp"), self.today)
            channel = r.get("channel", "").lower()
            direction = r.get("direction", "").lower()
            outcome = r.get("outcome", "").lower()
            if problem:
                self.excluded.append((i, problem))
                continue
            bad = [name for name, val, allowed in (("channel", channel, CHANNELS),
                                                   ("direction", direction, DIRECTIONS),
                                                   ("outcome", outcome, OUTCOMES)) if val not in allowed]
            if bad:
                self.excluded.append((i, "unknown {} value".format(" and ".join(bad))))
                continue
            pid = r.get("person_id", "")
            if not pid:
                self.discipline["missing person_id"] += 1
                self.excluded.append((i, "no person_id"))
                continue
            if channel == "email" and direction == "out" and outcome == "sent" and not r.get("angle"):
                self.discipline["email touch missing angle"] += 1
            if r.get("sequence") and not r.get("step"):
                self.discipline["sequence row missing step"] += 1
            book_account = self.people.get(pid, {}).get("account_id", "")
            if r.get("account_id") and book_account and r["account_id"] != book_account:
                self.excluded.append((i, "person and account disagree"))
                continue
            account = r.get("account_id") or book_account
            self.rows.append({
                "line": i, "day": day, "when": when, "person": pid, "account": account, "channel": channel,
                "direction": direction, "outcome": outcome, "angle": r.get("angle", ""),
                "opener": r.get("opener", ""), "step": r.get("step", ""), "sequence": r.get("sequence", ""),
                "play": r.get("play_id", "") or self.play_of.get(pid, ""),
            })

    def segment(self, row):
        by = self.cfg["funnel"]["segment_by"]
        acct = self.accounts.get(row["account"], {})
        if by == "persona":
            return self.people.get(row["person"], {}).get("persona") or "no persona"
        if by == "play":
            return row["play"] or "no play"
        if by == "industry":
            return acct.get("industry") or "unknown industry"
        if by == "tier":
            return acct.get("tier") or "no tier"
        industry = (acct.get("industry") or "").lower()
        size = parse_number(acct.get("employees"))
        for seg in self.cfg["segments"]:
            inds = [x.lower() for x in seg.get("industries", [])]
            if inds and industry not in inds:
                continue
            if size is None:
                continue
            if size < seg.get("size_min", 0) or size > seg.get("size_max", float("inf")):
                continue
            return seg["id"]
        return "outside segments"


# ---------------------------------------------------------------- period stats

def moment(row):
    """Ordering key for a log row: its timestamp key, or the start of its day (UTC) when there is none."""
    if row.get("when") is not None:
        return row["when"]
    day = row["day"]
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()


def period_stats(rows, cfg):
    touches = [r for r in rows if r["direction"] == "out" and r["channel"] in TOUCH_CHANNELS]
    people_touched = {r["person"] for r in touches}
    sent = [r for r in rows if r["channel"] == "email" and r["direction"] == "out" and r["outcome"] == "sent"]
    people_emailed = {r["person"] for r in sent}
    dials = [r for r in rows if r["channel"] == "call" and r["direction"] == "out"]
    connects = [r for r in dials if r["outcome"] in CONNECT]
    conversations = [r for r in dials if r["outcome"] in CONVERSATION]
    engaged_people = {r["person"] for r in rows if r["channel"] == "email" and r["outcome"] in ENGAGED}
    replied = engaged_people & people_emailed
    booked_all = {r["person"] for r in rows if r["outcome"] == "booked"}
    booked = booked_all & people_touched
    # A bounce counts only for a person emailed in this period, and only after that person's first send.
    first_send = {}
    for r in sent:
        if r["person"] not in first_send or moment(r) < first_send[r["person"]]:
            first_send[r["person"]] = moment(r)
    bounce_rows = [r for r in rows if r["channel"] == "email" and r["outcome"] == "bounced"]
    counted = [r for r in bounce_rows if r["person"] in first_send and moment(r) >= first_send[r["person"]]]
    bounces = sorted({r["person"] for r in counted})[:len(sent)]
    unmatched_bounces = len(bounce_rows) - len(counted)
    opt_outs = {r["person"] for r in rows if r["outcome"] == "opt_out"}
    s = {
        "touches": len(touches), "people_touched": len(people_touched), "emails_sent": len(sent),
        "people_emailed": len(people_emailed), "dials": len(dials), "connects": len(connects),
        "conversations": len(conversations), "replied_people": len(replied),
        "other_replies": len(engaged_people - people_emailed), "booked_people": len(booked),
        "booked_outside": len(booked_all - people_touched), "bounces": len(bounces),
        "bounces_outside": unmatched_bounces,
        "opt_outs": len(opt_outs),
        "_touched_set": people_touched, "_booked_set": booked, "_booked_all": booked_all,
    }
    s["reply_rate"] = rate_cell(len(replied), len(people_emailed), cfg)
    s["meeting_rate"] = rate_cell(len(booked), len(people_touched), cfg)
    s["connect_rate"] = rate_cell(len(connects), len(dials), cfg)
    s["conversation_rate"] = rate_cell(len(conversations), len(connects), cfg)
    s["bounce_rate"] = rate_cell(len(bounces), len(sent), cfg)
    return s


def bridge(cur_rows, prev_rows, seg_of):
    """Split the change in booked people into volume, rate and mix. Exact (Fractions)."""
    def per_segment(rows):
        touched, booked = {}, {}
        tset = {r["person"] for r in rows if r["direction"] == "out" and r["channel"] in TOUCH_CHANNELS}
        bset = {r["person"] for r in rows if r["outcome"] == "booked"} & tset
        first_seg = {}
        for r in rows:
            if r["person"] in tset and r["person"] not in first_seg:
                first_seg[r["person"]] = seg_of(r)
        for p in tset:
            touched[first_seg[p]] = touched.get(first_seg[p], 0) + 1
        for p in bset:
            booked[first_seg[p]] = booked.get(first_seg[p], 0) + 1
        return touched, booked

    t1, b1 = per_segment(cur_rows)
    t0, b0 = per_segment(prev_rows)
    segs = sorted(set(t0) | set(t1))
    new_segs = [s for s in segs if not t0.get(s) and t1.get(s)]
    old_segs = [s for s in segs if s not in new_segs]
    V0 = sum(t0.values())
    M0 = sum(b0.values())
    M1 = sum(b1.values())
    # Volume, rate and mix are measured on segments that existed in the prior period.
    # Touches and meetings in brand-new segments get their own line, so they never look like a rate change.
    V1 = sum(t1.get(s, 0) for s in old_segs)
    new_part = Fraction(sum(b1.get(s, 0) for s in new_segs))
    w0 = {s: Fraction(t0.get(s, 0), V0) if V0 else Fraction(0) for s in old_segs}
    w1 = {s: Fraction(t1.get(s, 0), V1) if V1 else Fraction(0) for s in old_segs}
    r0 = {s: Fraction(b0.get(s, 0), t0[s]) if t0.get(s) else Fraction(0) for s in old_segs}
    r1 = {s: Fraction(b1.get(s, 0), t1[s]) if t1.get(s) else Fraction(0) for s in old_segs}
    R0 = sum((w0[s] * r0[s] for s in old_segs), Fraction(0))
    volume = (V1 - V0) * R0
    mix = V1 * sum(((w1[s] - w0[s]) * r0[s] for s in old_segs), Fraction(0))
    rate = V1 * sum((w1[s] * (r1[s] - r0[s]) for s in old_segs), Fraction(0))
    rows = []
    for s in segs:
        is_new = s in new_segs
        rows.append({"segment": s, "prev_touched": t0.get(s, 0), "prev_booked": b0.get(s, 0),
                     "cur_touched": t1.get(s, 0), "cur_booked": b1.get(s, 0), "new": is_new,
                     "mix_part": Fraction(0) if is_new else V1 * (w1[s] - w0[s]) * r0[s],
                     "rate_part": Fraction(0) if is_new else V1 * w1[s] * (r1[s] - r0[s]),
                     "new_part": Fraction(b1.get(s, 0)) if is_new else Fraction(0)})
    return {"V0": V0, "V1": V1, "M0": M0, "M1": M1, "volume": volume, "rate": rate, "mix": mix,
            "new": new_part, "total": Fraction(M1 - M0), "segments": rows}


# ---------------------------------------------------------------- tests

def read_tests(path):
    if not path.exists():
        return []
    data = read_json(path)
    return data.get("tests", []) if isinstance(data, dict) else []


def evaluate_test(test, rows, cfg, today):
    f = cfg["funnel"]
    out = {"id": test.get("id", "?"), "kind": test.get("kind", "opener"), "problems": [], "arms": [],
           "off_plan": 0, "leader": None, "verdict": "", "next_up": None}
    arms = list(test.get("arms", []))
    variable = test.get("variable")
    if isinstance(variable, list) and len(variable) != 1:
        out["problems"].append("changes {} variables at once; no arm can be credited".format(len(variable)))
    elif not variable:
        out["problems"].append("no variable named")
    if len(arms) < 2:
        out["problems"].append("needs at least two arms")
    start = parse_date(test.get("start"))
    registered = parse_date(test.get("registered"))
    if not start:
        out["problems"].append("no start date")
    if registered is None:
        out["problems"].append("no registered date: treat results as exploratory")
    elif start and registered > start:
        out["problems"].append("registered after the test started: treat results as exploratory")
    if out["problems"] and (len(arms) < 2 or not start):
        out["verdict"] = "not readable"
        return out
    kind = out["kind"]
    minimum = test.get("min_per_arm") or (f["min_connects_per_arm"] if kind == "opener"
                                          else f["min_first_touches_per_angle"])
    out["min"] = minimum
    changes = {k: parse_date(v) for k, v in (test.get("script_changes") or {}).items()}
    units = {a: 0 for a in arms}
    wins = {a: 0 for a in arms}
    if kind == "opener":
        for r in rows:
            if r["channel"] != "call" or r["direction"] != "out" or r["opener"] not in arms:
                continue
            if r["day"] < start:
                continue
            if r["opener"] != assign_arm(out["id"], r["person"], arms):
                out["off_plan"] += 1
                continue
            since = changes.get(r["opener"])
            if since and r["day"] < since:
                continue
            if r["outcome"] in CONNECT:
                units[r["opener"]] += 1
                if r["outcome"] in CONVERSATION:
                    wins[r["opener"]] += 1
        out["unit"], out["metric"] = "connects", "conversations per connect"
    else:
        first = {}
        for r in sorted(rows, key=lambda x: (x["day"], x["line"])):
            if (r["channel"] == "email" and r["direction"] == "out" and r["outcome"] == "sent"
                    and r["step"] == "1" and r["angle"] in arms and r["day"] >= start
                    and r["person"] not in first):
                first[r["person"]] = r
        engaged_on = {}
        for r in rows:
            if r["channel"] == "email" and r["outcome"] in ENGAGED:
                engaged_on.setdefault(r["person"], []).append(r["day"])
        for pid, r in sorted(first.items()):
            if r["angle"] != assign_arm(out["id"], pid, arms):
                out["off_plan"] += 1
                continue
            since = changes.get(r["angle"])
            if since and r["day"] < since:
                continue
            units[r["angle"]] += 1
            if any(d >= r["day"] for d in engaged_on.get(pid, [])):
                wins[r["angle"]] += 1
        out["unit"], out["metric"] = "first touches", "people who replied per first touch"
    for a in arms:
        cell = rate_cell(wins[a], units[a], cfg)
        out["arms"].append({"arm": a, "units": units[a], "wins": wins[a], "cell": cell,
                            "restarted": changes.get(a).isoformat() if changes.get(a) else ""})
    out["next_up"] = min(arms, key=lambda a: (units[a], arms.index(a)))
    if all(units[a] >= minimum for a in arms) and not out["problems"]:
        ranked = sorted(out["arms"], key=lambda x: (-(x["wins"] / x["units"]), arms.index(x["arm"])))
        best = ranked[0]
        others = ranked[1:]
        if best["wins"] / best["units"] == others[0]["wins"] / others[0]["units"]:
            out["verdict"] = "tie at the minimum: keep testing"
        else:
            out["leader"] = best["arm"]
            overlap = any(not clear_difference(best["cell"], o["cell"]) for o in others)
            out["clear"] = not overlap
            out["verdict"] = ("leader {}: clear on the 95% ranges".format(best["arm"]) if not overlap else
                              "leader {} by point estimate only: the 95% ranges overlap".format(best["arm"]))
            if kind == "angle":
                out["losers"] = [o["arm"] for o in others]
    elif out["problems"]:
        out["verdict"] = "exploratory only"
    else:
        out["verdict"] = "running: not every arm has {} {} yet".format(minimum, out["unit"])
    return out


# ---------------------------------------------------------------- quota

def quota(cur, targets, period_days, cfg, cur_rows):
    if not targets:
        return None
    q = {"commit": targets.get("meetings_commit"), "stretch": targets.get("meetings_stretch"),
         "work_days": targets.get("work_days"), "period_days": targets.get("period_days", period_days)}
    q["matches_period"] = q["period_days"] == period_days
    cell = cur["meeting_rate"]
    q["rate"] = cell
    q["booked"] = cur["booked_people"]
    q["plan"] = []
    if cell["label"] != "measured" or cell["k"] == 0:
        q["unknown"] = True
        return q
    q["unknown"] = False
    for name in ("commit", "stretch"):
        target = q[name]
        if not target:
            continue
        need = math.ceil(target / cell["rate"])
        lo = math.ceil(target / cell["high"])
        hi = math.ceil(target / cell["low"]) if cell["low"] > 0 else None
        per_day = need / q["work_days"] if q["work_days"] else None
        q["plan"].append({"name": name, "target": target, "need": need, "lo": lo, "hi": hi,
                          "per_day": per_day, "gap": max(0, target - cur["booked_people"])})
    mins = cfg["funnel"]["minutes_per_touch"]
    levers = []
    for ch in sorted(TOUCH_CHANNELS):
        touches = sum(1 for r in cur_rows if r["channel"] == ch and r["direction"] == "out")
        booked = sum(1 for r in cur_rows if r["channel"] == ch and r["outcome"] == "booked")
        c = rate_cell(booked, touches, cfg)
        per_hour = (booked / touches) * 60.0 / mins.get(ch, 1) if touches and mins.get(ch) else 0.0
        levers.append({"channel": ch, "touches": touches, "booked": booked, "cell": c, "per_hour": per_hour})
    q["levers"] = sorted(levers, key=lambda x: (x["cell"]["label"] != "measured", -x["per_hour"], x["channel"]))
    return q


# ---------------------------------------------------------------- actions

PRIORITY = {"bounce": 0, "logging": 1, "quota": 2, "test": 3, "segment": 4, "drop": 5, "angle": 6}


def actions(cur, prev, seg_table, tests, q, data, cfg):
    f = cfg["funnel"]
    cands = []
    b = cur["bounce_rate"]
    if b["label"] == "measured":
        name = band(b["rate"], f["bounce_bands"])
        if name == "stop":
            cands.append(("bounce", b["n"], "Pause new email volume and verify addresses first: bounce rate {} is in "
                          "the stop band. Size: {} emails sent.".format(show(b), b["n"])))
        elif name == "watch":
            cands.append(("bounce", b["n"], "Check list quality before adding email volume: bounce rate {} is in the "
                          "watch band. Size: {} emails sent.".format(show(b), b["n"])))
    total_rows = len(data.rows) + len(data.excluded)
    gaps = sum(data.discipline.values()) + sum(1 for _, why in data.excluded if why != "no person_id")
    if total_rows and gaps / total_rows > f["logging_gap_share"]:
        cands.append(("logging", gaps, "Fix logging before trusting the rates: {} of {} log rows are excluded or "
                      "miss a field. Size: {} rows.".format(gaps, total_rows, gaps)))
    if q and not q.get("unknown"):
        for p in q["plan"]:
            if p["name"] == "commit" and p["gap"] > 0 and p["per_day"] is not None:
                extra = p["need"] - cur["people_touched"]
                if extra > 0:
                    cands.append(("quota", p["gap"], "Touch about {} more people this period ({:.1f} a work day in "
                                  "total) to reach the commit of {} meetings at the measured rate {}. Size: {} "
                                  "meetings short.".format(extra, p["per_day"], p["target"], show(q["rate"]), p["gap"])))
    for t in tests:
        if t.get("leader") and t.get("clear") and t["kind"] == "opener":
            best = [a for a in t["arms"] if a["arm"] == t["leader"]][0]
            cands.append(("test", sum(a["units"] for a in t["arms"]), "Use opener {} on every cold call in test {}: "
                          "{}. Size: {} connects in the test.".format(
                              t["leader"], t["id"], show(best["cell"]), sum(a["units"] for a in t["arms"]))))
        if t.get("leader") and t["kind"] == "angle":
            for loser in t.get("losers", []):
                arm = [a for a in t["arms"] if a["arm"] == loser][0]
                step = "cut it" if arm["restarted"] else "rewrite it once"
                cands.append(("angle", arm["units"], "Angle '{}' trails '{}' in test {}: {}; {}. Size: {} first "
                              "touches.".format(loser, t["leader"], t["id"], show(arm["cell"]), step, arm["units"])))
    for seg in seg_table:
        if clear_difference(seg["meeting"], seg["rest"]) and seg["meeting"]["rate"] < seg["rest"]["rate"]:
            cands.append(("segment", seg["meeting"]["n"], "Rework or pause segment {}: meeting rate {} against {} for "
                          "everyone else. Size: {} people touched.".format(
                              seg["segment"], show(seg["meeting"]), show(seg["rest"]), seg["meeting"]["n"])))
    for key, label in (("reply_rate", "reply rate"), ("meeting_rate", "meeting rate")):
        if clear_difference(prev[key], cur[key]) and cur[key]["rate"] < prev[key]["rate"]:
            cands.append(("drop", cur[key]["n"], "Find what changed in the {}: it fell from {} to {}. Size: {} "
                          "people.".format(label, show(prev[key]), show(cur[key]), cur[key]["n"])))
    cands.sort(key=lambda c: (PRIORITY[c[0]], -c[1], c[2]))
    return [c[2] for c in cands[:3]]


# ---------------------------------------------------------------- report

def fmt_frac(x):
    return "{:+.2f}".format(float(x))


def build(workspace, today, period_days, out_dir=None):
    workspace = Path(workspace)
    cfg = load_config(workspace)
    data = Data(workspace, today, cfg)
    cur_start = today - dt.timedelta(days=period_days)
    prev_start = today - dt.timedelta(days=2 * period_days)
    cur_rows = [r for r in data.rows if cur_start < r["day"] <= today]
    prev_rows = [r for r in data.rows if prev_start < r["day"] <= cur_start]
    cur = period_stats(cur_rows, cfg)
    prev = period_stats(prev_rows, cfg)
    lag = int(cfg["funnel"]["lag_lookback_days"])
    for stats, start in ((cur, cur_start), (prev, prev_start)):
        stats["booked_earlier"] = booked_from_earlier(data.rows, stats, start, lag)
    cohorts = cohort_table(data.rows, today, cfg)
    holdouts = holdout_lift(data, cur_rows, cfg)

    seg_of = data.segment
    seg_names = sorted({seg_of(r) for r in cur_rows})
    seg_table = []
    for s in seg_names:
        inside = [r for r in cur_rows if seg_of(r) == s]
        rest = [r for r in cur_rows if seg_of(r) != s]
        si, sr = period_stats(inside, cfg), period_stats(rest, cfg)
        seg_table.append({"segment": s, "meeting": si["meeting_rate"], "reply": si["reply_rate"],
                          "rest": sr["meeting_rate"]})
    br = bridge(cur_rows, prev_rows, seg_of)
    tests = [evaluate_test(t, data.rows, cfg, today) for t in read_tests(workspace / "funnel" / "tests.json")]
    targets_path = workspace / "funnel" / "targets.json"
    targets = read_json(targets_path) if targets_path.exists() else None
    q = quota(cur, targets, period_days, cfg, cur_rows)
    changes = []
    changes_path = workspace / "funnel" / "changes.csv"
    if changes_path.exists():
        for r in read_csv(changes_path):
            d = parse_date(r.get("date"))
            if d and cur_start < d <= today:
                changes.append((d, r.get("change", ""), r.get("area", "")))
    acts = actions(cur, prev, seg_table, tests, q, data, cfg)

    out_dir = Path(out_dir) if out_dir else workspace / "funnel"
    inputs = [p.resolve() for p in data.inputs + [workspace / "funnel" / "tests.json", targets_path,
                                                 changes_path, workspace / "gtm.json"]]
    for blocked in ("log", "book", "input", "plays", "signals"):
        if out_dir.resolve() == (workspace / blocked).resolve():
            raise ValueError("refusing to write into {}/: that folder holds inputs".format(blocked))
    report_path = out_dir / "report-{}.md".format(today.isoformat())
    metrics_path = out_dir / "metrics-{}.csv".format(today.isoformat())
    for p in (report_path, metrics_path):
        if p.resolve() in inputs:
            raise ValueError("refusing to write over an input file: {}".format(p))
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = render(today, period_days, cur_start, prev_start, data, cur, prev, seg_table, br, tests, q,
                   changes, acts, cfg, cohorts, holdouts)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_metrics(metrics_path, cur, prev, seg_table, tests, cohorts)
    return {"report": report_path, "metrics": metrics_path, "actions": acts, "bridge": br, "current": cur,
            "prior": prev, "tests": tests, "quota": q, "excluded": data.excluded, "segments": seg_table,
            "cohorts": cohorts, "holdouts": holdouts}


def booked_from_earlier(rows, stats, start, lookback_days):
    """People booked in the period who were not touched in it but were touched in the
    lookback window just before it. Shown in the headline, kept out of every rate."""
    window = start - dt.timedelta(days=lookback_days)
    earlier = {r["person"] for r in rows if r["direction"] == "out" and r["channel"] in TOUCH_CHANNELS
               and window < r["day"] <= start}
    in_period = stats["_touched_set"]
    booked_outside = stats.get("_booked_all", set()) - in_period
    return len(booked_outside & earlier)


def holdout_lift(data, cur_rows, cfg):
    """For each play with a holdout: the meeting rate of people the play worked against the
    people it left alone, both counted on bookings in the current period."""
    booked = {r["person"] for r in cur_rows if r["outcome"] == "booked"}
    out = []
    for play, g in sorted(data.groups.items()):
        if not g["holdout"]:
            continue
        treated = rate_cell(len(g["treated"] & booked), len(g["treated"]), cfg)
        held = rate_cell(len(g["holdout"] & booked), len(g["holdout"]), cfg)
        out.append({"play": play, "treated": treated, "holdout": held, "clear": clear_difference(treated, held)})
    return out


def monday(day):
    return day - dt.timedelta(days=day.weekday())


def cohort_table(rows, today, cfg):
    """Meeting rate by the week of each person's first outbound touch. A week is mature
    once cohort_maturation_days have passed since its last day."""
    f = cfg["funnel"]
    first = {}
    for r in rows:
        if r["direction"] == "out" and r["channel"] in TOUCH_CHANNELS:
            if r["person"] not in first or r["day"] < first[r["person"]]:
                first[r["person"]] = r["day"]
    booked = {r["person"] for r in rows if r["outcome"] == "booked"}
    oldest = monday(today) - dt.timedelta(weeks=int(f["cohort_weeks"]) - 1)
    weeks = {}
    for person, day in first.items():
        wk = monday(day)
        if wk >= oldest:
            weeks.setdefault(wk, set()).add(person)
    out = []
    for wk in sorted(weeks):
        people = weeks[wk]
        k = len(people & booked)
        last_day = wk + dt.timedelta(days=6)
        out.append({"week": wk.isoformat(), "people": len(people), "booked": k,
                    "cell": rate_cell(k, len(people), cfg),
                    "mature": (today - last_day).days >= int(f["cohort_maturation_days"])})
    return out


def write_metrics(path, cur, prev, seg_table, tests, cohorts=()):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["period", "scope", "metric", "numerator", "denominator", "rate", "ci_low", "ci_high", "label"])

        def row(period, scope, metric, cell):
            def num(x):
                return "" if x is None else "{:.4f}".format(x)
            w.writerow([period, scope, metric, cell["k"], cell["n"], num(cell["rate"]), num(cell["low"]),
                        num(cell["high"]), cell["label"]])
        for period, s in (("prior", prev), ("current", cur)):
            for key in ("reply_rate", "meeting_rate", "connect_rate", "conversation_rate", "bounce_rate"):
                row(period, "overall", key, s[key])
        for seg in seg_table:
            row("current", "segment:" + seg["segment"], "meeting_rate", seg["meeting"])
            row("current", "segment:" + seg["segment"], "reply_rate", seg["reply"])
        for t in tests:
            for a in t["arms"]:
                row("test", "test:{}:{}".format(t["id"], a["arm"]), t.get("metric", ""), a["cell"])
        for c in cohorts:
            row("cohort", "week:" + c["week"] + ("" if c["mature"] else " (not mature)"), "meeting_rate", c["cell"])


def render(today, period_days, cur_start, prev_start, data, cur, prev, seg_table, br, tests, q, changes, acts, cfg,
           cohorts=(), holdouts=()):
    f = cfg["funnel"]
    L = []
    L.append("# Funnel review: {} days ending {}".format(period_days, today.isoformat()))
    L.append("")
    L.append("## Scope and limits")
    L.append("")
    L.append("- Current period: {} to {}. Prior period: {} to {}.".format(
        (cur_start + dt.timedelta(days=1)).isoformat(), today.isoformat(),
        (prev_start + dt.timedelta(days=1)).isoformat(), cur_start.isoformat()))
    L.append("- Inputs read: {}.".format(", ".join(sorted({p.relative_to(data.ws).as_posix()
                                                         for p in data.inputs}))))
    L.append("- Log rows used: {}. Excluded: {}.".format(len(data.rows), len(data.excluded)))
    L.append("- A rate needs at least {} people or events behind it. Below {} it is an anecdote, not a rate. "
             "Ranges are 95% Wilson intervals; zero events use the rule of three.".format(
                 f["min_n_rate"], f["anecdote_n"]))
    L.append("- Labels: **measured** (a rate with enough behind it), **observed pattern** (counted, too few to "
             "rate), **inference** (an explanation, never measured).")
    L.append("")
    L.append("## Headline numbers")
    L.append("")
    L.append("| Measure | Prior | Current | Clear change? |")
    L.append("|---|---|---|---|")
    for label, key in (("Touches (out)", "touches"), ("People touched", "people_touched"),
                       ("Emails sent", "emails_sent"), ("Dials", "dials"), ("Connects", "connects"),
                       ("Conversations", "conversations"), ("People booked", "booked_people")):
        L.append("| {} | {} | {} | count |".format(label, prev[key], cur[key]))
    L.append("| Booked from earlier touches (not in the rate) | {} | {} | count |".format(
        prev["booked_earlier"], cur["booked_earlier"]))
    for label, key in (("Reply rate (people replied / people emailed)", "reply_rate"),
                       ("Meeting rate (people booked / people touched)", "meeting_rate"),
                       ("Connect rate (connects / dials)", "connect_rate"),
                       ("Conversation rate (conversations / connects)", "conversation_rate"),
                       ("Bounce rate (bounces / emails sent)", "bounce_rate")):
        clear = "yes" if clear_difference(prev[key], cur[key]) else "no"
        L.append("| {} | {} | {} | {} |".format(label, show(prev[key]), show(cur[key]), clear))
    if cur["bounce_rate"]["label"] == "measured":
        L.append("")
        L.append("Bounce band: **{}**.".format(band(cur["bounce_rate"]["rate"], f["bounce_bands"])))
    if cur["other_replies"] or cur["booked_outside"]:
        L.append("")
        L.append("Context, not in any rate: {} people replied without an email this period; {} people booked "
                 "without a touch this period.".format(cur["other_replies"], cur["booked_outside"]))
    if cur["bounces_outside"]:
        L.append("")
        L.append("Context, not in the bounce rate: {} bounce row(s) belong to people not emailed this period, or "
                 "came before their send. A bounce counts only after a send in the same period.".format(
                     cur["bounces_outside"]))
    L.append("")
    L.append("## By {} (current period)".format(f["segment_by"]))
    L.append("")
    L.append("Each rate uses only the people that {} could reach. The book-wide total is context, never the "
             "denominator.".format(f["segment_by"]))
    L.append("")
    L.append("| {} | Meeting rate | Reply rate | Everyone else's meeting rate |".format(f["segment_by"].capitalize()))
    L.append("|---|---|---|---|")
    for s in seg_table:
        L.append("| {} | {} | {} | {} |".format(s["segment"], show(s["meeting"]), show(s["reply"]), show(s["rest"])))
    alarms = base_alarms(cur, seg_table, cfg)
    if alarms:
        L.append("")
        L.append("**Check the base.**")
        L += ["- " + a for a in alarms]
    L.append("")
    L.append("## Cohorts by first-touch week")
    L.append("")
    if cohorts:
        L.append("Each person counts once, in the week of their first touch, with every meeting booked since. "
                 "A week is mature {} days after its last day; judge only mature weeks.".format(
                     f["cohort_maturation_days"]))
        L.append("")
        L.append("| Week of | People first touched | Booked so far | Meeting rate | Mature? |")
        L.append("|---|---|---|---|---|")
        for c in cohorts:
            L.append("| {} | {} | {} | {} | {} |".format(c["week"], c["people"], c["booked"], show(c["cell"]),
                                                       "yes" if c["mature"] else "not yet"))
    else:
        L.append("No first touches in the last {} weeks.".format(f["cohort_weeks"]))
    if holdouts:
        L.append("")
        L.append("## Play holdouts")
        L.append("")
        L.append("Meeting rate this period for people each play worked and for its holdout, the accounts it "
                 "left alone on purpose. Only non-overlapping 95% ranges count as a clear difference.")
        L.append("")
        L.append("| Play | Worked | Holdout | Clear difference? |")
        L.append("|---|---|---|---|")
        for h in holdouts:
            L.append("| {} | {} | {} | {} |".format(h["play"], show(h["treated"]), show(h["holdout"]),
                                                   "yes" if h["clear"] else "no"))
    L.append("")
    L.append("## Why meetings moved")
    L.append("")
    L.append("People booked went from {} to {} (change {}). Split by {}:".format(
        br["M0"], br["M1"], fmt_frac(br["total"]), f["segment_by"]))
    L.append("")
    L.append("| Part | Meetings |")
    L.append("|---|---|")
    L.append("| Volume (more or fewer people touched, at the old rate) | {} |".format(fmt_frac(br["volume"])))
    L.append("| Rate (conversion changed inside segments) | {} |".format(fmt_frac(br["rate"])))
    L.append("| Mix (the share of each segment changed) | {} |".format(fmt_frac(br["mix"])))
    L.append("| New segment (no touches last period, so no old rate to compare) | {} |".format(
        fmt_frac(br["new"])))
    L.append("| **Total** | **{}** |".format(fmt_frac(br["volume"] + br["rate"] + br["mix"] + br["new"])))
    L.append("")
    L.append("| Segment | Prior touched | Prior booked | Current touched | Current booked | Mix part | Rate part | "
             "New segment |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in br["segments"]:
        L.append("| {}{} | {} | {} | {} | {} | {} | {} | {} |".format(
            s["segment"], " (new)" if s["new"] else "", s["prev_touched"], s["prev_booked"], s["cur_touched"],
            s["cur_booked"], fmt_frac(s["mix_part"]), fmt_frac(s["rate_part"]), fmt_frac(s["new_part"])))
    L.append("")
    count_conf = "measured" if cur["meeting_rate"]["label"] == "measured" else cur["meeting_rate"]["label"]
    L.append("- Confidence in the counts: {}. Confidence in any cause: inference until tested.".format(count_conf))
    if len(changes) > 1:
        L.append("- {} changes shipped this period ({}). They overlap, so none is credited for the movement.".format(
            len(changes), "; ".join(c[1] for c in sorted(changes))))
    elif len(changes) == 1:
        L.append("- One change shipped this period: {} ({}). It may explain part of the movement; inference, not "
                 "measured.".format(changes[0][1], changes[0][0].isoformat()))
    else:
        L.append("- No changes were logged in funnel/changes.csv for this period.")
    L.append("- Other causes to rule out before naming one: list quality, logging gaps, time of year, and who was "
             "touched (the mix line above measures only the segment share).")
    L.append("")
    L.append("## Tests")
    L.append("")
    if not tests:
        L.append("No tests in funnel/tests.json.")
    for t in tests:
        L.append("### {} ({})".format(t["id"], t["kind"]))
        L.append("")
        for p in t["problems"]:
            L.append("- Problem: {}.".format(p))
        if t["arms"]:
            L.append("- Metric: {}. Minimum per arm: {} {}.".format(t["metric"], t["min"], t["unit"]))
            for a in t["arms"]:
                extra = " (count restarted {} after a script change)".format(a["restarted"]) if a["restarted"] else ""
                L.append("- Arm {}: {} {}; {}{}.".format(a["arm"], a["units"], t["unit"], show(a["cell"]), extra))
            if t["off_plan"]:
                L.append("- {} rows used an arm other than the one the person was assigned. They are reported "
                         "apart and not counted.".format(t["off_plan"]))
            L.append("- Next up: arm {} (fewest {}).".format(t["next_up"], t["unit"]))
        L.append("- Verdict: {}.".format(t["verdict"]))
        L.append("")
    L.append("## Quota")
    L.append("")
    if q is None:
        L.append("No targets in funnel/targets.json.")
    else:
        if not q["matches_period"]:
            L.append("- Note: targets are for {} days; this review covers {}.".format(q["period_days"], period_days))
        if q["unknown"]:
            L.append("- Unknown: the meeting rate is {}. Do not plan from it; gather more data first.".format(
                show(q["rate"])))
        else:
            L.append("- Measured meeting rate: {}. Booked so far: {}.".format(show(q["rate"]), q["booked"]))
            for p in q["plan"]:
                hi = "no upper bound" if p["hi"] is None else str(p["hi"])
                per_day = "" if p["per_day"] is None else ", about {:.1f} a work day".format(p["per_day"])
                L.append("- {}: {} meetings needs about {} people touched (range {} to {}){}.".format(
                    p["name"].capitalize(), p["target"], p["need"], p["lo"], hi, per_day))
            L.append("")
            L.append("| Channel | Touches | Booked | Booked per touch | Meetings per hour |")
            L.append("|---|---|---|---|---|")
            for lv in q["levers"]:
                L.append("| {} | {} | {} | {} | {:.2f} |".format(lv["channel"], lv["touches"], lv["booked"],
                                                                 show(lv["cell"]), lv["per_hour"]))
    L.append("")
    L.append("## Patterns")
    L.append("")
    booked_rows = [r for r in data.rows if r["outcome"] == "booked"
                   and cur_start < r["day"] <= today and r["person"] in cur["_booked_set"]]
    m = len(cur["_booked_set"])
    if m:
        by_channel = {}
        by_play = {}
        seen = set()
        for r in sorted(booked_rows, key=lambda x: (x["day"], x["line"])):
            if r["person"] in seen:
                continue
            seen.add(r["person"])
            by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + 1
            key = r["play"] or "no play"
            by_play[key] = by_play.get(key, 0) + 1
        names = {"call": "a call", "email": "an email", "linkedin": "a LinkedIn touch", "meeting": "a meeting"}
        for k in sorted(by_channel):
            L.append("- {} of {} people booked were booked on {}.".format(by_channel[k], m, names.get(k, k)))
        for k in sorted(by_play):
            L.append("- {} of {} people booked came from {}.".format(by_play[k], m, k))
    elif cur["booked_earlier"]:
        L.append("- Nobody touched this period has booked yet; {} people booked this period came from earlier "
                 "touches (see the cohort table).".format(cur["booked_earlier"]))
    else:
        L.append("- Nobody was booked this period.")
    L.append("")
    L.append("## Data checks")
    L.append("")
    reasons = {}
    for _, why in data.excluded:
        reasons[why] = reasons.get(why, 0) + 1
    if not reasons and not any(data.discipline.values()):
        L.append("- No problems found in the log.")
    for why in sorted(reasons):
        L.append("- Excluded: {} row(s) with {}.".format(reasons[why], why))
    for key in sorted(data.discipline):
        if data.discipline[key] and key != "missing person_id":
            L.append("- Kept but incomplete: {} row(s) with {}.".format(data.discipline[key], key))
    L.append("")
    L.append("## Actions")
    L.append("")
    if acts:
        for i, a in enumerate(acts, 1):
            L.append("{}. {}".format(i, a))
    else:
        L.append("Nothing needs to change.")
    L.append("")
    L.append("Nothing was sent, enrolled or written to any system. This report only reads your files.")
    return L


def main(argv=None):
    ap = argparse.ArgumentParser(description="Review the outbound funnel from the activity log.")
    ap.add_argument("--workspace", default="gtm", help="GTM workspace folder (default ./gtm)")
    ap.add_argument("--today", required=True, help="YYYY-MM-DD, the last day of the current period")
    ap.add_argument("--period-days", type=int, default=30, help="length of each period in days (default 30)")
    ap.add_argument("--out", help="folder for the report (default <workspace>/funnel)")
    args = ap.parse_args(argv)
    try:
        today = dt.date.fromisoformat(args.today)
    except ValueError:
        ap.error("--today must be YYYY-MM-DD")
    if args.period_days < 1:
        ap.error("--period-days must be 1 or more")
    try:
        res = build(args.workspace, today, args.period_days, args.out)
    except (ValueError, OSError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    cur, prev = res["current"], res["prior"]
    print("Funnel review written to {}".format(res["report"]))
    print("  people touched: {} (prior {})".format(cur["people_touched"], prev["people_touched"]))
    print("  meeting rate: {}".format(show(cur["meeting_rate"])))
    print("  reply rate: {}".format(show(cur["reply_rate"])))
    print("  excluded log rows: {}".format(len(res["excluded"])))
    print("  actions: {}".format(len(res["actions"]) or "nothing needs to change"))
    print("Nothing was sent or written to any system.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
