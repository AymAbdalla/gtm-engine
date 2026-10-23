"""Rule checks for aym-gtm funnel-review (funnel_report.py) on made-up data."""
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "aym-gtm" / "skills" / "funnel-review"
EXAMPLE = SKILL / "assets" / "example"
spec = importlib.util.spec_from_file_location("funnel_report", SKILL / "scripts" / "funnel_report.py")
fr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr)

TODAY = dt.date(2026, 10, 20)
LOG_COLS = ["activity_id", "timestamp", "person_id", "account_id", "channel", "direction", "sequence", "step",
            "play_id", "angle", "opener", "outcome", "notes", "source"]
ACCT_COLS = ["account_id", "name", "domain", "employees", "industry", "country", "tier", "status"]
CFG = {"funnel": json.loads(json.dumps(fr.DEFAULTS)), "segments": []}


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


class Log:
    """Builds activity rows with sequential ids."""

    def __init__(self):
        self.rows = []

    def add(self, day, person, channel, direction, outcome, account="A1", **kw):
        stamp = kw.pop("timestamp", "{}T10:00:00-04:00".format(day))
        row = {"activity_id": "a{}".format(len(self.rows) + 1), "timestamp": stamp, "person_id": person,
               "account_id": account, "channel": channel, "direction": direction, "outcome": outcome,
               "source": "manual"}
        row.update(kw)
        self.rows.append(row)
        return self


def rows_for(log, today=TODAY):
    """Normalize rows the way the script does, for unit tests of period_stats."""
    out = []
    for i, r in enumerate(log.rows, 2):
        day, when, problem = fr.parse_moment(r["timestamp"], today)
        if problem:
            continue
        out.append({"line": i, "day": day, "when": when, "person": r["person_id"], "account": r["account_id"],
                    "channel": r["channel"], "direction": r["direction"], "outcome": r["outcome"],
                    "angle": r.get("angle", ""), "opener": r.get("opener", ""), "step": r.get("step", ""),
                    "sequence": r.get("sequence", ""), "play": r.get("play_id", "")})
    return out


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "gtm"
        (self.ws / "funnel").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, log, accounts=None, gtm=None, tests=None, targets=None):
        write_csv(self.ws / "log" / "activity.csv", LOG_COLS, log.rows)
        if accounts:
            write_csv(self.ws / "book" / "accounts.csv", ACCT_COLS, accounts)
        if gtm is not None:
            (self.ws / "gtm.json").write_text(json.dumps(gtm))
        if tests is not None:
            (self.ws / "funnel" / "tests.json").write_text(json.dumps({"tests": tests}))
        if targets is not None:
            (self.ws / "funnel" / "targets.json").write_text(json.dumps(targets))

    def run_build(self, period=7):
        return fr.build(self.ws, TODAY, period, self.ws / "out")

    def report(self):
        return (self.ws / "out" / "report-{}.md".format(TODAY.isoformat())).read_text()


class Formulas(unittest.TestCase):
    def test_counts_and_rates_follow_the_written_formulas(self):
        log = Log()
        d = "2026-10-15"
        # three people emailed; one replies, one replies twice (counts once)
        for p in ("p1", "p2", "p3"):
            log.add(d, p, "email", "out", "sent", angle="trigger")
        log.add(d, "p1", "email", "in", "replied").add(d, "p2", "email", "in", "interested")
        log.add(d, "p2", "email", "in", "replied")
        # someone who replied without being emailed: context only
        log.add(d, "p9", "email", "in", "replied")
        # calls: answered outcomes count as connects; bad_number, gatekeeper, voicemail and no_answer do not
        for outcome in ("connected", "not_now", "booked", "bad_number", "gatekeeper", "voicemail", "no_answer"):
            log.add(d, "p4", "call", "out", outcome)
        # a booking for someone never touched does not count in the meeting rate
        log.add(d, "p8", "meeting", "in", "booked")
        log.add(d, "p3", "email", "in", "bounced")
        s = fr.period_stats(rows_for(log), CFG)
        self.assertEqual(s["dials"], 7)
        self.assertEqual(s["connects"], 3)
        self.assertEqual(s["conversations"], 2)
        self.assertEqual(s["people_emailed"], 3)
        self.assertEqual(s["replied_people"], 2)
        self.assertEqual(s["other_replies"], 1)
        self.assertEqual(s["people_touched"], 4)
        self.assertEqual(s["booked_people"], 1)
        self.assertEqual(s["booked_outside"], 1)
        self.assertEqual(s["bounces"], 1)
        self.assertEqual((s["reply_rate"]["k"], s["reply_rate"]["n"]), (2, 3))
        self.assertEqual((s["meeting_rate"]["k"], s["meeting_rate"]["n"]), (1, 4))
        self.assertEqual((s["conversation_rate"]["k"], s["conversation_rate"]["n"]), (2, 3))


class Bounces(Workspace):
    def test_more_bounce_rows_than_sends_never_crashes_or_exceeds_the_base(self):
        log = Log()
        prev, cur = "2026-10-08", "2026-10-15"
        for i in range(20):
            log.add(prev, "o{}".format(i), "email", "out", "sent", angle="trigger")
        for i in range(20):
            log.add(cur, "n{}".format(i), "email", "out", "sent", angle="trigger")
        # 25 bounce rows this period: 20 for last period's people (not emailed now), 5 for this period's
        for i in range(20):
            log.add(cur, "o{}".format(i), "email", "in", "bounced")
        for i in range(5):
            log.add(cur, "n{}".format(i), "email", "in", "bounced")
        self.write(log)
        res = self.run_build(period=7)
        b = res["current"]["bounce_rate"]
        self.assertEqual((b["k"], b["n"]), (5, 20))
        self.assertLessEqual(b["k"], b["n"])
        self.assertEqual(res["current"]["bounces_outside"], 20)
        self.assertIn("Context, not in the bounce rate: 20 bounce row(s)", self.report())

    def test_bounce_before_the_send_does_not_count(self):
        log = Log()
        log.add("2026-10-15", "p1", "email", "in", "bounced", timestamp="2026-10-15T09:00:00-04:00")
        log.add("2026-10-15", "p1", "email", "out", "sent", angle="trigger", timestamp="2026-10-15T11:00:00-04:00")
        log.add("2026-10-15", "p2", "email", "out", "sent", angle="trigger", timestamp="2026-10-15T08:00:00-04:00")
        log.add("2026-10-15", "p2", "email", "in", "bounced", timestamp="2026-10-15T08:05:00-04:00")
        s = fr.period_stats(rows_for(log), CFG)
        self.assertEqual(s["bounces"], 1)
        self.assertEqual(s["bounces_outside"], 1)

    def test_wilson_refuses_more_events_than_base(self):
        with self.assertRaises(ValueError):
            fr.wilson(25, 20, 1.96)
        cell = fr.rate_cell(25, 20, CFG)
        self.assertTrue(cell["label"].startswith("invalid"))
        self.assertIsNone(cell["low"])


class PlayAttribution(Workspace):
    def test_live_approved_row_wins_over_a_blocked_one(self):
        cols = ["play_id", "person_id", "account_id", "seat", "sequence", "sequence_start",
                "variables", "rank", "approved", "drop_reason"]
        base = {"account_id": "A1", "seat": "", "sequence": "s", "sequence_start": "2026-10-01",
                "variables": "{}", "rank": "1"}
        write_csv(self.ws / "plays" / "a-old" / "enroll.csv", cols,
                  [dict(base, play_id="a-old", person_id="p1", approved="yes",
                        drop_reason="was approved, now blocked: account on hold")])
        write_csv(self.ws / "plays" / "b-new" / "enroll.csv", cols,
                  [dict(base, play_id="b-new", person_id="p1", approved="yes", drop_reason=""),
                   dict(base, play_id="b-new", person_id="p2", approved="", drop_reason="")])
        self.write(Log())
        data = fr.Data(self.ws, TODAY, fr.load_config(self.ws))
        self.assertEqual(data.play_of, {"p1": "b-new"})


class AccountCheck(Workspace):
    def test_person_and_account_disagree_is_excluded(self):
        write_csv(self.ws / "book" / "people.csv", ["person_id", "account_id", "persona"],
                  [{"person_id": "p1", "account_id": "A1"}, {"person_id": "p2", "account_id": "A2"}])
        log = Log()
        log.add("2026-10-15", "p1", "email", "out", "sent", account="A1", angle="trigger")
        log.add("2026-10-15", "p2", "email", "out", "sent", account="A9", angle="trigger")
        self.write(log)
        res = self.run_build(period=7)
        self.assertEqual(res["current"]["emails_sent"], 1)
        self.assertIn((3, "person and account disagree"), res["excluded"])
        self.assertIn("person and account disagree", self.report())


class BaseAlarm(unittest.TestCase):
    def test_rate_far_above_benchmark_asks_to_check_the_base(self):
        cfg = {"funnel": dict(fr.DEFAULTS, benchmarks={"meeting_rate": 0.02, "reply_rate": 0.05})}
        hot = fr.rate_cell(12, 30, cfg)          # 40% meetings: 20 times the benchmark
        calm = fr.rate_cell(3, 30, cfg)          # 10% replies: 2 times
        few = fr.rate_cell(3, 4, cfg)            # too few to rate: never alarms
        seg_table = [{"segment": "logistics", "meeting": hot, "reply": calm, "rest": calm},
                     {"segment": "tiny", "meeting": few, "reply": few, "rest": calm}]
        alarms = fr.base_alarms({"meeting_rate": calm, "reply_rate": calm}, seg_table, cfg)
        self.assertEqual(len(alarms), 1)
        self.assertIn("logistics meeting rate", alarms[0])
        self.assertIn("check who is in the denominator", alarms[0])
        none = fr.base_alarms({}, seg_table, {"funnel": dict(fr.DEFAULTS)})
        self.assertEqual(none, [])               # no benchmarks set, no alarms


class Statistics(unittest.TestCase):
    def test_wilson_interval_matches_known_values(self):
        low, high = fr.wilson(5, 20, 1.96)
        self.assertAlmostEqual(low, 0.1119, places=3)
        self.assertAlmostEqual(high, 0.4687, places=3)
        low, high = fr.wilson(20, 20, 1.96)
        self.assertAlmostEqual(low, 0.8389, places=3)
        self.assertEqual(high, 1.0)

    def test_zero_events_use_the_rule_of_three(self):
        self.assertEqual(fr.wilson(0, 30, 1.96), (0.0, 0.1))
        self.assertEqual(fr.wilson(0, 2, 1.96), (0.0, 1.0))
        self.assertEqual(fr.wilson(0, 0, 1.96), (None, None))

    def test_sample_floors(self):
        self.assertEqual(fr.rate_cell(0, 0, CFG)["label"], "no data")
        self.assertEqual(fr.rate_cell(1, 4, CFG)["label"], "anecdote, not a rate")
        tiny = fr.rate_cell(3, 12, CFG)
        self.assertEqual(tiny["label"], "too few to rate")
        self.assertIsNone(tiny["rate"])
        self.assertIn("too few to rate", fr.show(tiny))
        ok = fr.rate_cell(5, 20, CFG)
        self.assertEqual(ok["label"], "measured")
        self.assertAlmostEqual(ok["rate"], 0.25)

    def test_clear_difference_needs_two_measured_rates_and_no_overlap(self):
        a, b = fr.rate_cell(2, 40, CFG), fr.rate_cell(30, 40, CFG)
        self.assertTrue(fr.clear_difference(a, b))
        self.assertFalse(fr.clear_difference(fr.rate_cell(9, 40, CFG), fr.rate_cell(12, 40, CFG)))
        self.assertFalse(fr.clear_difference(fr.rate_cell(0, 10, CFG), b))


class StableHash(unittest.TestCase):
    def test_assignment_is_a_stable_sha256_split(self):
        arms = ["A", "B", "C"]
        for pid in ("p001", "p002", "p777"):
            expect = arms[int(hashlib.sha256("opener-x:{}".format(pid).encode()).hexdigest(), 16) % 3]
            self.assertEqual(fr.assign_arm("opener-x", pid, arms), expect)
            self.assertEqual(fr.assign_arm("opener-x", pid, arms), fr.assign_arm("opener-x", pid, list(arms)))
        seen = {fr.assign_arm("opener-x", "p{:03d}".format(i), arms) for i in range(60)}
        self.assertEqual(seen, set(arms))

    def test_different_tests_split_independently(self):
        a = [fr.assign_arm("t1", "p{}".format(i), ["X", "Y"]) for i in range(40)]
        b = [fr.assign_arm("t2", "p{}".format(i), ["X", "Y"]) for i in range(40)]
        self.assertNotEqual(a, b)


class Bridge(Workspace):
    SEGS = [{"id": "logi", "industries": ["logistics"], "size_min": 1, "size_max": 5000},
            {"id": "mfg", "industries": ["manufacturing"], "size_min": 1, "size_max": 5000},
            {"id": "soft", "industries": ["software"], "size_min": 1, "size_max": 5000}]
    ACCTS = [{"account_id": "L", "industry": "logistics", "employees": "500"},
             {"account_id": "M", "industry": "manufacturing", "employees": "1,200"},
             {"account_id": "S", "industry": "software", "employees": "300"}]

    def scenario(self):
        log = Log()
        prev, cur = "2026-10-08", "2026-10-17"
        # prior: logistics 6 touched / 3 booked, manufacturing 4 / 1, software none
        for i in range(6):
            log.add(prev, "pl{}".format(i), "call", "out", "booked" if i < 3 else "connected", account="L")
        for i in range(4):
            log.add(prev, "pm{}".format(i), "call", "out", "booked" if i < 1 else "no_answer", account="M")
        # current: logistics 3 / 1, manufacturing 9 / 2, software (new) 2 / 1
        for i in range(3):
            log.add(cur, "ql{}".format(i), "call", "out", "booked" if i < 1 else "connected", account="L")
        for i in range(9):
            log.add(cur, "qm{}".format(i), "email", "out", "sent", account="M", angle="trigger")
            if i < 2:
                log.add(cur, "qm{}".format(i), "email", "in", "booked", account="M")
        for i in range(2):
            log.add(cur, "qs{}".format(i), "call", "out", "booked" if i < 1 else "voicemail", account="S")
        return log

    def test_volume_rate_and_mix_add_up_exactly(self):
        self.write(self.scenario(), accounts=self.ACCTS, gtm={"segments": self.SEGS})
        res = self.run_build(period=7)
        br = res["bridge"]
        self.assertEqual((br["M0"], br["M1"]), (4, 4))
        self.assertIsInstance(br["volume"], Fraction)
        self.assertEqual(br["volume"] + br["rate"] + br["mix"] + br["new"], br["total"])
        self.assertEqual(br["total"], Fraction(0))
        self.assertEqual(sum((s["mix_part"] for s in br["segments"]), Fraction(0)), br["mix"])
        self.assertEqual(sum((s["rate_part"] for s in br["segments"]), Fraction(0)), br["rate"])
        # volume: 12 touched now in segments that existed before, vs 10 before, at the old rate 4/10
        self.assertEqual(br["volume"], Fraction(2) * Fraction(4, 10))
        self.assertIn("| **Total** | **+0.00** |", self.report())

    def test_new_segment_gets_its_own_line_not_rate(self):
        self.write(self.scenario(), accounts=self.ACCTS, gtm={"segments": self.SEGS})
        br = self.run_build(period=7)["bridge"]
        # software had nobody last period: its 1 booking is the new-segment part, not a rate change
        self.assertEqual(br["new"], Fraction(1))
        new_rows = [s for s in br["segments"] if s["new"]]
        self.assertEqual(len(new_rows), 1)
        self.assertEqual((new_rows[0]["rate_part"], new_rows[0]["mix_part"]), (Fraction(0), Fraction(0)))
        self.assertIn("New segment (no touches last period", self.report())
        self.assertIn("(new) |", self.report())

    def test_denominator_rule_per_segment(self):
        self.write(self.scenario(), accounts=self.ACCTS, gtm={"segments": self.SEGS})
        res = self.run_build(period=7)
        seg = {s["segment"]: s for s in res["segments"]}
        # manufacturing's reply rate uses only manufacturing people emailed (9), not everyone touched (14)
        self.assertEqual((seg["mfg"]["reply"]["k"], seg["mfg"]["reply"]["n"]), (2, 9))
        self.assertEqual(seg["mfg"]["meeting"]["n"], 9)
        self.assertEqual(seg["logi"]["meeting"]["n"], 3)
        self.assertEqual(seg["mfg"]["rest"]["n"], 5)
        self.assertIn("never the denominator", self.report())


class Exclusions(Workspace):
    def test_future_blank_and_unknown_rows_are_excluded_and_reported(self):
        log = Log()
        log.add("2026-10-15", "p1", "email", "out", "sent", angle="trigger")
        log.add("2026-10-15", "p2", "email", "out", "sent", timestamp="2026-10-25T09:00:00-04:00")
        log.add("2026-10-15", "p3", "email", "out", "sent", timestamp="")
        log.add("2026-10-15", "p4", "call", "out", "left_voicemail")
        log.add("2026-10-15", "p5", "email", "out", "sent")              # kept, but no angle
        self.write(log)
        res = self.run_build()
        reasons = sorted(why for _, why in res["excluded"])
        self.assertEqual(reasons, ["blank timestamp", "timestamp after today (treated as blank)",
                                   "unknown outcome value"])
        self.assertEqual(res["current"]["emails_sent"], 2)
        text = self.report()
        self.assertIn("1 row(s) with email touch missing angle", text)

    def test_refuses_to_write_into_input_folders(self):
        self.write(Log().add("2026-10-15", "p1", "email", "out", "sent", angle="x"))
        with self.assertRaises(ValueError):
            fr.build(self.ws, TODAY, 7, self.ws / "log")
        before = (self.ws / "log" / "activity.csv").read_bytes()
        self.assertEqual(before, (self.ws / "log" / "activity.csv").read_bytes())

    def test_missing_log_is_an_error(self):
        with self.assertRaises(ValueError):
            fr.build(self.ws, TODAY, 7, self.ws / "out")


class Tests(Workspace):
    def opener_log(self, per_arm, conversations, start="2026-10-01"):
        arms = ["A", "B"]
        log, made = Log(), {a: 0 for a in arms}
        i = 0
        while min(made.values()) < per_arm:
            pid = "p{:03d}".format(i)
            i += 1
            arm = fr.assign_arm("op", pid, arms)
            if made[arm] >= per_arm:
                continue
            outcome = "interested" if made[arm] < conversations[arm] else "connected"
            log.add("2026-10-10", pid, "call", "out", outcome, opener=arm)
            made[arm] += 1
        return log

    def test_leader_only_when_every_arm_has_the_minimum(self):
        test = {"id": "op", "kind": "opener", "variable": "opener", "arms": ["A", "B"], "min_per_arm": 20,
                "registered": "2026-09-30", "start": "2026-10-01"}
        self.write(self.opener_log(12, {"A": 1, "B": 10}), tests=[test])
        t = self.run_build(period=30)["tests"][0]
        self.assertIsNone(t["leader"])
        self.assertIn("running", t["verdict"])

    def test_clear_leader_and_off_plan_rows_reported_apart(self):
        test = {"id": "op", "kind": "opener", "variable": "opener", "arms": ["A", "B"], "min_per_arm": 20,
                "registered": "2026-09-30", "start": "2026-10-01"}
        log = self.opener_log(25, {"A": 2, "B": 20})
        wrong = "B" if fr.assign_arm("op", "zz1", ["A", "B"]) == "A" else "A"
        log.add("2026-10-11", "zz1", "call", "out", "booked", opener=wrong)
        self.write(log, tests=[test])
        res = self.run_build(period=30)
        t = res["tests"][0]
        self.assertEqual(t["leader"], "B")
        self.assertTrue(t["clear"])
        self.assertEqual(t["off_plan"], 1)
        self.assertEqual(sum(a["units"] for a in t["arms"]), 50)
        self.assertEqual(t["next_up"], "A")

    def test_script_change_restarts_an_arm_count(self):
        test = {"id": "op", "kind": "opener", "variable": "opener", "arms": ["A", "B"], "min_per_arm": 5,
                "registered": "2026-09-30", "start": "2026-10-01", "script_changes": {"A": "2026-10-12"}}
        self.write(self.opener_log(6, {"A": 3, "B": 3}), tests=[test])
        t = self.run_build(period=30)["tests"][0]
        arm_a = [a for a in t["arms"] if a["arm"] == "A"][0]
        self.assertEqual(arm_a["units"], 0)
        self.assertEqual(t["next_up"], "A")

    def test_registered_late_or_two_variables_is_exploratory(self):
        late = {"id": "op", "kind": "opener", "variable": ["opener", "time"], "arms": ["A", "B"],
                "min_per_arm": 5, "registered": "2026-10-05", "start": "2026-10-01"}
        self.write(self.opener_log(6, {"A": 1, "B": 5}), tests=[late])
        t = self.run_build(period=30)["tests"][0]
        self.assertIsNone(t["leader"])
        self.assertEqual(t["verdict"], "exploratory only")
        self.assertTrue(any("registered after" in p for p in t["problems"]))
        self.assertTrue(any("2 variables" in p for p in t["problems"]))


class Ending(Workspace):
    def test_nothing_needs_to_change_when_no_action_qualifies(self):
        log = Log()
        for i in range(25):
            log.add("2026-10-15", "p{}".format(i), "email", "out", "sent", angle="trigger")
        self.write(log)
        res = self.run_build()
        self.assertEqual(res["actions"], [])
        self.assertIn("## Actions\n\nNothing needs to change.", self.report())

    def test_at_most_three_actions_each_with_a_size(self):
        log = Log()
        prev, cur = "2026-10-08", "2026-10-17"
        for i in range(40):                                   # prior: high reply and meeting rates
            log.add(prev, "o{}".format(i), "email", "out", "sent", angle="trigger")
            if i < 30:
                log.add(prev, "o{}".format(i), "email", "in", "booked")
        for i in range(40):                                   # current: low rates, many bounces
            log.add(cur, "n{}".format(i), "email", "out", "sent", angle="trigger")
            if i < 8:
                log.add(cur, "n{}".format(i), "email", "in", "bounced")
            if i == 9:
                log.add(cur, "n{}".format(i), "email", "in", "booked")
        self.write(log, targets={"period_days": 7, "meetings_commit": 10, "work_days": 5})
        res = self.run_build()
        self.assertEqual(len(res["actions"]), 3)
        self.assertTrue(res["actions"][0].startswith("Pause new email volume"))
        for a in res["actions"]:
            self.assertIn("Size:", a)
        text = self.report()
        self.assertIn("\n3. ", text)
        self.assertNotIn("\n4. ", text)

    def test_quota_is_unknown_when_the_rate_is_not_measured(self):
        log = Log().add("2026-10-15", "p1", "email", "out", "sent", angle="x").add("2026-10-15", "p1", "email",
                                                                                  "in", "booked")
        self.write(log, targets={"period_days": 7, "meetings_commit": 4, "work_days": 5})
        res = self.run_build()
        self.assertTrue(res["quota"]["unknown"])
        self.assertIn("Do not plan from it", self.report())


class LagAndCohorts(Workspace):
    """Oct 22 review probe: 10 meetings booked this week from last week's emails read as zero."""

    def probe(self):
        log = Log()
        for i in range(25):
            log.add("2026-10-12", "early{}".format(i), "email", "out", "sent", angle="trigger")
        for i in range(10):
            log.add("2026-10-15", "early{}".format(i), "email", "in", "booked")
        for i in range(25):
            log.add("2026-10-19", "late{}".format(i), "email", "out", "sent", angle="trigger")
        self.write(log)

    def test_bookings_from_earlier_touches_are_in_the_headline(self):
        self.probe()
        res = self.run_build(7)
        self.assertEqual(res["current"]["booked_earlier"], 10)
        text = res["report"].read_text()
        self.assertIn("| Booked from earlier touches (not in the rate) | 0 | 10 |", text)
        self.assertNotIn("Nobody was booked this period", text)

    def test_cohort_table_by_first_touch_week(self):
        self.probe()
        res = self.run_build(7)
        cohorts = {c["week"]: c for c in res["cohorts"]}
        self.assertEqual((cohorts["2026-10-12"]["people"], cohorts["2026-10-12"]["booked"]), (25, 10))
        self.assertFalse(cohorts["2026-10-12"]["mature"])        # matures 21 days after its last first touch
        self.assertEqual((cohorts["2026-10-19"]["people"], cohorts["2026-10-19"]["booked"]), (25, 0))
        self.assertIn("## Cohorts by first-touch week", res["report"].read_text())

    def test_default_period_is_30_days(self):
        self.probe()
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fr.main(["--workspace", str(self.ws), "--today", "2026-10-20",
                                      "--out", str(self.ws / "out")]), 0)
        self.assertIn("# Funnel review: 30 days ending 2026-10-20",
                      (self.ws / "out/report-2026-10-20.md").read_text())


class HoldoutLift(Workspace):
    """play-build's holdout rows let the review compare a play with accounts it left alone."""

    def test_play_and_holdout_rates_side_by_side(self):
        log = Log()
        for i in range(20):
            log.add("2026-10-05", "t{}".format(i), "email", "out", "sent", angle="trigger", play_id="p1")
        for i in range(6):
            log.add("2026-10-12", "t{}".format(i), "email", "in", "booked")
        log.add("2026-10-12", "h0", "email", "in", "booked")
        self.write(log)
        enroll = [{"play_id": "p1", "person_id": "t{}".format(i), "account_id": "A{}".format(i), "approved": "yes",
                   "drop_reason": ""} for i in range(20)]
        enroll += [{"play_id": "p1", "person_id": "h{}".format(i), "account_id": "H{}".format(i), "approved": "",
                    "drop_reason": "holdout: kept untouched so the play can be measured"} for i in range(20)]
        write_csv(self.ws / "plays/p1/enroll.csv", ["play_id", "person_id", "account_id", "approved", "drop_reason"],
                  enroll)
        res = self.run_build(30)
        lift = {h["play"]: h for h in res["holdouts"]}
        self.assertEqual((lift["p1"]["treated"]["k"], lift["p1"]["treated"]["n"]), (6, 20))
        self.assertEqual((lift["p1"]["holdout"]["k"], lift["p1"]["holdout"]["n"]), (1, 20))
        self.assertFalse(lift["p1"]["clear"])    # the 95% ranges overlap at this size
        text = res["report"].read_text()
        self.assertIn("## Play holdouts", text)
        self.assertIn("6 of 20", text)
        self.assertIn("1 of 20", text)


class Example(unittest.TestCase):
    def test_example_matches_the_expected_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "gtm"
            shutil.copytree(EXAMPLE, ws)
            shutil.rmtree(ws / "expected")
            res = fr.build(ws, TODAY, 30)
            for name in ("report-2026-10-20.md", "metrics-2026-10-20.csv"):
                self.assertEqual((ws / "funnel" / name).read_text(),
                                 (EXAMPLE / "expected" / name).read_text(), name)
            br = res["bridge"]
            self.assertEqual(br["volume"] + br["rate"] + br["mix"] + br["new"], br["total"])
            self.assertLessEqual(len(res["actions"]), 3)

    def test_example_config_matches_the_shared_config_plus_funnel(self):
        mine = json.loads((EXAMPLE / "gtm.json").read_text())
        shared = json.loads((SKILL.parent / "icp-define" / "assets" / "example" / "gtm.json").read_text())
        self.assertIn("funnel", mine)
        mine.pop("funnel")
        shared.pop("funnel", None)
        self.assertEqual(mine, shared)


if __name__ == "__main__":
    unittest.main()
