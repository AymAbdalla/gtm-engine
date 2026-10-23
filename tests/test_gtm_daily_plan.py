"""Rules for aym-gtm daily-plan: sequence date math, stops, queue, call slots, nudge and close."""
import csv
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/daily-plan"
spec = importlib.util.spec_from_file_location("plan_day", SKILL / "scripts/plan_day.py")
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)
EXAMPLE = SKILL / "assets/example"
CFG = json.loads((EXAMPLE / "gtm.json").read_text())

PEOPLE = ["person_id", "account_id", "first_name", "last_name", "title", "email", "email_status", "email_score",
          "phone", "linkedin_url", "country", "timezone", "status", "last_touch_date", "sequence", "tags", "notes",
          "crm_id", "source", "persona", "lane", "role", "send_ok", "send_block_reason", "followup_ok",
          "followup_block_reason", "call_ok", "call_block_reason", "timezone_source", "next_step", "new_note"]
ACCTS = ["account_id", "name", "domain", "tier", "status"]
ENROLL = ["play_id", "person_id", "account_id", "seat", "sequence", "sequence_start", "variables", "rank",
          "approved", "drop_reason"]
LOG = ["activity_id", "timestamp", "person_id", "account_id", "channel", "direction", "sequence", "step", "play_id",
       "angle", "opener", "outcome", "notes", "source"]
SEQ = {"sequences": [{"id": "s1", "version": 1, "variables": {}, "steps": [
    {"day": 1, "order": 1, "channel": "email", "thread": "new", "subject": "Hi {{company}}", "body": "Hi {{first_name}}, {{fact}}?"},
    {"day": 2, "order": 1, "channel": "call", "thread": "new", "subject": "", "body": "Call about {{fact}}"},
    {"day": 4, "order": 1, "channel": "email", "thread": "reply", "subject": "", "body": "{{first_name}}, following up?"},
    {"day": 7, "order": 1, "channel": "linkedin", "thread": "new", "subject": "", "body": "Hi {{first_name}}"}]}]}


def write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def person(pid, aid="A1", **kw):
    row = {"person_id": pid, "account_id": aid, "first_name": pid.title(), "last_name": "Test", "title": "Controller",
           "email": f"{pid}@acme.example", "email_status": "verified", "email_score": "95",
           "phone": "+1-312-555-0100", "linkedin_url": f"https://linkedin.example/in/{pid}", "country": "US",
           "timezone": "America/Chicago", "status": "active", "role": "champion", "persona": "controller",
           "send_ok": "yes", "followup_ok": "no", "call_ok": "yes"}
    row.update(kw)
    return row


def enroll(pid, start, aid="A1", fact="you are hiring", approved="yes", play="p1"):
    return {"play_id": play, "person_id": pid, "account_id": aid, "sequence": "s1", "sequence_start": start,
            "variables": json.dumps({"fact": fact} if fact is not None else {}), "approved": approved}


def act(i, ts, pid, step="", outcome="sent", channel="email", direction="out", aid="A1", seq="s1", notes=""):
    return {"activity_id": i, "timestamp": ts, "person_id": pid, "account_id": aid, "channel": channel,
            "direction": direction, "sequence": seq, "step": step, "outcome": outcome, "notes": notes,
            "source": "manual"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "gtm"
        self.ws.mkdir()
        cfg = json.loads(json.dumps(CFG))
        cfg["daily"]["holidays"] = []
        self.cfg = cfg
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        (self.ws / "outreach").mkdir()
        (self.ws / "outreach/sequences.json").write_text(json.dumps(SEQ))
        write(self.ws / "book/accounts.csv", ACCTS, [{"account_id": "A1", "name": "Acme", "tier": "P1", "status": "active"},
                                                     {"account_id": "A2", "name": "Bolt", "tier": "P2", "status": "active"}])

    def tearDown(self):
        self.tmp.cleanup()

    def setup(self, people, enrolls=(), log=()):
        write(self.ws / "book/people.csv", PEOPLE, people)
        write(self.ws / "plays/p1/enroll.csv", ENROLL, list(enrolls))
        write(self.ws / "log/activity.csv", LOG, list(log))

    def plan(self, day):
        ws = pd.Workspace(self.ws, day)
        return ws, pd.build_plan(ws, day)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pd.main(["--workspace", str(self.ws)] + list(argv))
        return code, out.getvalue() + err.getvalue()


class LiveDealTests(Base):
    """Oct 22 review probe: a live-deal account the book had marked re-engage."""

    def setUp(self):
        super().setUp()
        write(self.ws / "book/accounts.csv", ACCTS + ["strategy", "owner"], [
            {"account_id": "A1", "name": "Acme", "tier": "P1", "status": "live_deal", "strategy": "re-engage"},
            {"account_id": "A2", "name": "Bolt", "tier": "P2", "status": "active", "strategy": "automated"}])

    def test_no_extra_touch_at_a_live_deal_account(self):
        self.setup([person("ann", "A1", role="decision_maker", tags="past_reply", notes="x"),
                    person("bo", "A2", notes="x")])
        _, plan = self.plan(date(2026, 10, 20))
        names = {c["person_id"] for c in plan["cards"]}
        self.assertNotIn("ann", names)
        self.assertIn("bo", names)
        self.assertTrue(any("live_deal" in r for r in plan["dropped"]), plan["dropped"])

    def test_sequence_stops_at_a_live_deal_account(self):
        self.setup([person("ann", "A1")], [enroll("ann", "2026-10-20")])
        _, plan = self.plan(date(2026, 10, 20))
        self.assertEqual(plan["cards"], [])
        self.assertTrue(any("live_deal" in s["reason"] for s in plan["stopped"]), plan["stopped"])

    def test_open_deals_are_not_a_tie_break_bonus_by_default(self):
        self.assertNotIn("has_deal", pd.DEFAULT_DAILY["fact_ladder"])
        self.assertNotIn("has_deal", CFG["daily"]["fact_ladder"])


class StatedDefaultTests(Base):
    """D1 (Oct 22): a read-only plan may use a stated default, and says which one."""

    def test_no_date_plans_today_in_your_time_zone_and_says_so(self):
        from datetime import datetime, timezone
        self.setup([person("bo", "A2", notes="x")])
        tz = self.cfg["daily"]["user_timezone"]
        offset = pd.utc_offset(tz, datetime.now(timezone.utc).date())
        today = (datetime.now(timezone.utc) + offset).date()
        code, out = self.cli()
        self.assertEqual(code, 0, out)
        if pd.is_business_day(today, set()):
            text = (self.ws / "plan" / f"{today.isoformat()}.md").read_text()
            self.assertIn(f"No date was given, so this is the plan for today, {today.isoformat()}", text)
        else:
            self.assertIn("not a business day", out)

    def test_do_first_names_no_prep_cards(self):
        self.setup([person("bo", "A2", notes="")])
        _, plan = self.plan(date(2026, 10, 20))
        self.assertTrue(plan["cards"] and all(c["status"] == "no_prep" for c in plan["cards"]))
        line = pd.first_action(plan)
        self.assertNotIn("needs_human", line)
        self.assertIn("no_prep", line)


class DateMathTests(unittest.TestCase):
    def test_business_days_skip_weekends_and_holidays(self):
        h = {"2026-10-16"}
        self.assertEqual(pd.add_business_days(date(2026, 10, 13), 3, h), date(2026, 10, 19))
        self.assertEqual(pd.add_business_days(date(2026, 10, 17), 0, h), date(2026, 10, 19))   # Saturday rolls forward
        self.assertEqual(pd.business_days_between(date(2026, 10, 15), date(2026, 10, 20), h), 2)

    def test_fallback_offsets_match_daylight_saving_rule(self):
        saved = pd.ZoneInfo
        try:
            pd.ZoneInfo = None
            self.assertEqual(pd.utc_offset("America/New_York", date(2026, 10, 20)).total_seconds(), -4 * 3600)
            self.assertEqual(pd.utc_offset("America/New_York", date(2026, 11, 2)).total_seconds(), -5 * 3600)
            self.assertEqual(pd.utc_offset("America/Chicago", date(2026, 3, 9)).total_seconds(), -5 * 3600)
            self.assertEqual(pd.utc_offset("America/Phoenix", date(2026, 7, 1)).total_seconds(), -7 * 3600)
            self.assertIsNone(pd.utc_offset("Mars/Base", date(2026, 7, 1)))
        finally:
            pd.ZoneInfo = saved
        if saved is not None:
            for tz in ("America/New_York", "America/Los_Angeles", "Pacific/Honolulu"):
                for d in (date(2026, 3, 9), date(2026, 10, 20), date(2026, 11, 2)):
                    pd.ZoneInfo = None
                    fb = pd.utc_offset(tz, d)
                    pd.ZoneInfo = saved
                    self.assertEqual(fb, pd.utc_offset(tz, d), (tz, d))


class SequenceTests(Base):
    def card(self, plan, pid):
        return next((c for c in plan["cards"] if c["person_id"] == pid and c["kind"] == "sequence"), None)

    def test_overdue_step_is_planned_today_with_a_shift_note(self):
        # start Mon 10-12; step 2 (day 2) due 10-13, never worked; today Wed 10-14
        self.setup([person("a", sequence="s1", send_ok="no", followup_ok="yes")], [enroll("a", "2026-10-12")],
                   [act("1", "2026-10-12T09:00:00-04:00", "a", "1")])
        _, plan = self.plan(date(2026, 10, 14))
        c = self.card(plan, "a")
        self.assertEqual((c["channel"], c["step"]), ("call", "2"))
        self.assertIn("move 1 business day", c["why"])

    def test_late_work_pushes_later_steps_back(self):
        # step 2 due 10-13 but worked 10-14 (1 late): step 3 (day 4, due 10-15) moves to 10-16
        self.setup([person("a", sequence="s1", send_ok="no", followup_ok="yes")], [enroll("a", "2026-10-12")],
                   [act("1", "2026-10-12T09:00:00-04:00", "a", "1"),
                    act("2", "2026-10-14T15:00:00-04:00", "a", "2", outcome="no_answer", channel="call")])
        _, plan = self.plan(date(2026, 10, 15))
        self.assertIsNone(self.card(plan, "a"))
        _, plan = self.plan(date(2026, 10, 16))
        self.assertEqual(self.card(plan, "a")["step"], "3")
        self.assertEqual(self.card(plan, "a")["why"], "")

    def test_step_that_cannot_be_done_is_skipped_not_missed(self):
        self.setup([person("a", sequence="s1", send_ok="no", followup_ok="yes", phone="", call_ok="no",
                           call_block_reason="no phone")],
                   [enroll("a", "2026-10-12")], [act("1", "2026-10-12T09:00:00-04:00", "a", "1")])
        _, plan = self.plan(date(2026, 10, 15))      # day 4: step 3 due today, on schedule
        c = self.card(plan, "a")
        self.assertEqual((c["step"], c["why"]), ("3", ""))
        self.assertEqual([(s["step"], s["reason"]) for s in plan["skipped"]], [(2, "call gate: no phone")])

    def test_reply_stops_the_person_and_the_whole_account(self):
        self.setup([person("a", sequence="s1", send_ok="no", followup_ok="yes"),
                    person("b", sequence="s1", send_ok="no", followup_ok="yes"),
                    person("c", aid="A2", sequence="s1", send_ok="no", followup_ok="yes")],
                   [enroll("a", "2026-10-12"), enroll("b", "2026-10-12"), enroll("c", "2026-10-12", aid="A2")],
                   [act("1", "2026-10-13T11:00:00-04:00", "a", "", outcome="replied", direction="in")])
        _, plan = self.plan(date(2026, 10, 14))
        stopped = {s["person_id"]: s["reason"] for s in plan["stopped"]}
        self.assertIn("replied", stopped["a"])
        self.assertIn("someone at this account", stopped["b"])
        self.assertNotIn("c", stopped)

    def test_unfilled_variable_needs_a_human(self):
        self.setup([person("a")], [enroll("a", "2026-10-14", fact="")])
        _, plan = self.plan(date(2026, 10, 14))
        c = self.card(plan, "a")
        self.assertEqual(c["status"], "needs_human")
        self.assertIn("fill: fact", c["why"])

    def test_quoted_fact_shows_its_source_to_open(self):
        e = enroll("a", "2026-10-14")
        e["variables"] = json.dumps({"fact": "Acme posted a job", "trigger_fact": "Acme posted a job",
                                     "source_url": "https://jobs.example/1"})
        self.setup([person("a"), person("b", aid="A2")], [e, enroll("b", "2026-10-14", aid="A2")])
        _, plan = self.plan(date(2026, 10, 14))
        self.assertEqual(self.card(plan, "a")["source"], "https://jobs.example/1")
        self.assertIn("open it before this touch", pd.card_md(dict(self.card(plan, "a"), card_id="x")))
        self.assertEqual(self.card(plan, "b")["source"], "")

    def test_stop_status_and_unapproved_rows(self):
        self.setup([person("a", status="do_not_contact"), person("b")],
                   [enroll("a", "2026-10-14"), enroll("b", "2026-10-14", approved="")])
        _, plan = self.plan(date(2026, 10, 14))
        self.assertEqual(plan["stopped"][0]["reason"], "status is do_not_contact")
        self.assertIsNone(self.card(plan, "b"))

    def test_plan_ignores_todays_rows_so_a_rerun_matches(self):
        self.setup([person("a")], [enroll("a", "2026-10-14")])
        _, before = self.plan(date(2026, 10, 14))
        write(self.ws / "log/activity.csv", LOG, [act("1", "2026-10-14T09:00:00-04:00", "a", "1")])
        _, after = self.plan(date(2026, 10, 14))
        self.assertEqual(self.card(before, "a")["step"], self.card(after, "a")["step"])

    def test_future_timestamp_is_reported_and_still_counts(self):
        self.setup([person("a", sequence="s1", send_ok="no", followup_ok="yes")], [enroll("a", "2026-10-12")],
                   [act("1", "2026-12-12T09:00:00-05:00", "a", "1")])
        ws, plan = self.plan(date(2026, 10, 13))
        self.assertTrue(any("after today" in p for p in ws.problems))
        self.assertEqual(self.card(plan, "a")["step"], "2")

    def test_two_approved_plays_plan_only_the_first(self):
        self.setup([person("a")], [enroll("a", "2026-10-14")])
        write(self.ws / "plays/p2/enroll.csv", ENROLL, [enroll("a", "2026-10-14", play="p2")])
        ws, plan = self.plan(date(2026, 10, 14))
        self.assertEqual(self.card(plan, "a")["play_id"], "p1")
        self.assertTrue(any("two plays" in p for p in ws.problems))


class CallTests(Base):
    def test_calls_land_in_the_prospects_hours_and_calendar_busy_is_removed(self):
        self.cfg["daily"]["call_blocks"] = [{"name": "am", "start": "09:30", "end": "10:00"},
                                            {"name": "pm", "start": "14:00", "end": "15:00"}]
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("la", timezone="America/Los_Angeles", tags="inbound"),
                    person("hi", aid="A2", timezone="Pacific/Honolulu")])
        write(self.ws / "plan/calendar.csv", ["start", "end", "title"],
              [{"start": "2026-10-14T14:00:00-04:00", "end": "2026-10-14T14:30:00-04:00", "title": "busy"},
               {"start": "2026-10-14 15:00", "end": "2026-10-14 15:30", "title": "no offset"}])
        ws, plan = self.plan(date(2026, 10, 14))
        cards = {c["person_id"]: c for c in plan["cards"]}
        self.assertEqual(cards["la"]["slot_start"], "14:30 America/New_York")      # 9:30 ET is 6:30 in LA
        self.assertEqual(cards["la"]["prospect_local"], "11:30 America/Los_Angeles")
        self.assertEqual(cards["hi"]["prospect_local"], "08:35 Pacific/Honolulu")   # legal hours only, second pass
        self.assertTrue(any("no UTC offset" in p for p in ws.problems))

    def test_unknown_time_zone_needs_a_human_and_no_legal_slot_skips(self):
        self.cfg["daily"]["call_blocks"] = [{"name": "early", "start": "07:00", "end": "07:30"}]
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("x", timezone=""), person("la", aid="A2", sequence="s1", send_ok="no", followup_ok="yes",
                                                     timezone="America/Los_Angeles")],
                   [enroll("la", "2026-10-13", aid="A2")], [act("1", "2026-10-13T09:00:00-04:00", "la", "1", aid="A2")])
        _, plan = self.plan(date(2026, 10, 14))
        cards = {c["person_id"]: c for c in plan["cards"]}
        self.assertEqual(cards["x"]["status"], "needs_human")
        self.assertNotIn("la", cards)
        self.assertIn("outside calling hours", plan["skipped"][0]["reason"])


class QueueTests(Base):
    def test_flat_scores_fall_back_to_the_fact_ladder(self):
        self.cfg["daily"]["flat_gap"] = 1.1   # force flat
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("old", last_touch_date="2026-09-01", title="Controller", notes="2026-09-01: met"),
                    person("chief", aid="A2", title="Chief Financial Officer", role="decision_maker", notes="x")])
        _, plan = self.plan(date(2026, 10, 14))
        extras = [c for c in plan["cards"] if c["kind"] == "extra"]
        self.assertEqual([c["person_id"] for c in extras], ["chief", "old"])   # never touched beats touched
        self.assertTrue(all(c["score"] == "" for c in extras))
        self.assertTrue(plan["flat"])

    def test_score_shows_its_parts(self):
        self.cfg["daily"]["flat_gap"] = 0.0   # never flat
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("old", last_touch_date="2026-09-01", title="Controller", notes="2026-09-01: met"),
                    person("chief", aid="A2", title="Chief Financial Officer", role="decision_maker", notes="x")])
        _, plan = self.plan(date(2026, 10, 14))
        extras = [c for c in plan["cards"] if c["kind"] == "extra"]
        self.assertFalse(plan["flat"])
        for c in extras:
            self.assertIn("seat ", c["score_parts"])
            self.assertIn("recency ", c["score_parts"])
        md = pd.card_md(dict(extras[0], card_id="x-1"))
        self.assertIn("(parts, value x weight: ", md)

    def test_no_prep_line_sinks_and_recent_touch_is_left_out(self):
        self.setup([person("noprep", notes=""), person("prep", aid="A2", notes="2026-10-01: asked for pricing"),
                    person("recent", aid="A2", last_touch_date="2026-10-13", notes="x")])
        _, plan = self.plan(date(2026, 10, 14))
        extras = [c for c in plan["cards"] if c["kind"] == "extra"]
        self.assertEqual(extras[-1]["person_id"], "noprep")
        self.assertEqual(extras[-1]["status"], "no_prep")
        self.assertEqual(plan["dropped"].get("touched too recently"), 1)


class LinkedInGateTests(Base):
    def _linkedin_people(self, day=date(2026, 10, 14)):
        _, plan = self.plan(day)
        return {c["person_id"]: c for c in plan["cards"] if c["channel"] == "linkedin"}, plan

    def test_book_linkedin_gate_is_respected(self):
        cols = PEOPLE + ["linkedin_ok", "linkedin_block_reason"]
        rows = [person("open", phone="", call_ok="no", send_ok="no", notes="x", linkedin_ok="yes"),
                person("shut", aid="A2", phone="", call_ok="no", send_ok="no", notes="x",
                       linkedin_ok="no", linkedin_block_reason="title is not a buyer")]
        write(self.ws / "book/people.csv", cols, rows)
        write(self.ws / "plays/p1/enroll.csv", ENROLL, [])
        write(self.ws / "log/activity.csv", LOG, [])
        li, plan = self._linkedin_people()
        self.assertIn("open", li)
        self.assertEqual(li["open"]["block"], "linkedin_only")
        self.assertNotIn("shut", li)
        self.assertEqual(plan["dropped"].get("no usable channel for an extra touch"), 1)

    def test_old_book_without_linkedin_gate_still_blocks_who_must_never_be_touched(self):
        accts = ["account_id", "name", "domain", "tier", "status", "relationship", "strategy"]
        write(self.ws / "book/accounts.csv", accts, [
            {"account_id": "A1", "name": "Acme", "tier": "P1", "status": "active", "strategy": "automated"},
            {"account_id": "A2", "name": "Rival", "tier": "P2", "status": "active", "relationship": "competitor",
             "strategy": "excluded"},
            {"account_id": "A3", "name": "Paused", "tier": "P2", "status": "hold", "strategy": "hold"},
            {"account_id": "A4", "name": "Dealco", "tier": "P1", "status": "live_deal", "strategy": "live"},
            {"account_id": "A5", "name": "Fine", "tier": "P2", "status": "active", "strategy": "automated"}])
        no_path = dict(phone="", call_ok="no", send_ok="no", notes="x")
        self.setup([person("buyer", **no_path),
                    person("rep", aid="A5", title="Sales Representative", **no_path),
                    person("rival", aid="A2", title="CFO", **no_path),
                    person("held", aid="A3", **no_path),
                    person("deal", aid="A4", **no_path),
                    person("asked", aid="A5", phone="", call_ok="no", send_ok="no",
                           notes="2026-10-01: please do not contact me again")])
        li, _ = self._linkedin_people()
        self.assertEqual(sorted(li), ["buyer"])


class StopAndOwnerTests(Base):
    """A lasting stop outcome in the log, the account owner, and replies anywhere at the account."""

    def card(self, plan, pid):
        return next((c for c in plan["cards"] if c["person_id"] == pid), None)

    def test_lasting_stop_outcomes_end_every_touch(self):
        self.setup([person("optout", notes="x"),
                    person("wrong", aid="A2", phone="", call_ok="no", send_ok="no", notes="x"),
                    person("seq", sequence="s1", send_ok="no", followup_ok="yes")],
                   [enroll("seq", "2026-10-19")],
                   [act("1", "2026-10-02T10:00:00-04:00", "optout", outcome="opt_out", channel="call", seq="",
                        notes="said never call again"),
                    act("2", "2026-10-05T10:00:00-04:00", "wrong", outcome="wrong_person", channel="linkedin",
                        seq="", aid="A2"),
                    act("3", "2026-09-20T10:00:00-04:00", "seq", outcome="not_interested", channel="call", seq="")])
        _, plan = self.plan(date(2026, 10, 20))
        self.assertIsNone(self.card(plan, "optout"))
        self.assertIsNone(self.card(plan, "wrong"))
        stopped = {s["person_id"]: s["reason"] for s in plan["stopped"]}
        self.assertIn("not_interested on 2026-09-20", stopped["seq"])     # before the start still stops
        self.assertEqual(plan["dropped"].get(
            "log outcome ends every touch (opt out, not interested, wrong person or left)"), 2)

    def test_accounts_owned_by_someone_else_are_never_planned(self):
        write(self.ws / "book/accounts.csv", ACCTS + ["owner"], [
            {"account_id": "A1", "name": "Acme", "tier": "P1", "status": "active", "owner": "jordan"},
            {"account_id": "A2", "name": "Bolt", "tier": "P2", "status": "active", "owner": "Sam"},
            {"account_id": "A3", "name": "Cove", "tier": "P2", "status": "active", "owner": ""}])
        self.cfg["daily"]["owner"] = "sam"
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("theirs", notes="x"), person("theirs_seq", sequence="s1"),
                    person("mine", aid="A2", notes="x"), person("blank", aid="A3", notes="x")],
                   [enroll("theirs_seq", "2026-10-20")])
        _, plan = self.plan(date(2026, 10, 20))
        self.assertIsNone(self.card(plan, "theirs"))
        self.assertEqual({s["person_id"]: s["reason"] for s in plan["stopped"]}["theirs_seq"],
                         "account owned by jordan")
        self.assertIsNotNone(self.card(plan, "mine"))      # owner match ignores case
        self.assertIsNotNone(self.card(plan, "blank"))     # a blank owner counts as yours
        self.assertEqual(plan["dropped"].get("account owned by someone else"), 1)

    def test_owner_falls_back_to_the_play_owner(self):
        write(self.ws / "book/accounts.csv", ACCTS + ["owner"], [
            {"account_id": "A1", "name": "Acme", "tier": "P1", "status": "active", "owner": "sam"}])
        self.cfg["daily"].pop("owner", None)
        self.cfg.setdefault("play", {})["owner"] = "Sam"
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("a", notes="x")])
        _, plan = self.plan(date(2026, 10, 20))
        self.assertIsNotNone(self.card(plan, "a"))

    def test_reply_before_the_start_and_blank_account_still_stop_the_account(self):
        self.setup([person("a", sequence="s1"), person("b", sequence="s1"), person("c", aid="A2", sequence="s1")],
                   [enroll("a", "2026-10-19"), enroll("c", "2026-10-19", aid="A2")],
                   [act("1", "2026-10-16T11:00:00-04:00", "b", outcome="replied", direction="in", seq=""),
                    act("2", "2026-10-15T11:00:00-04:00", "zz", outcome="replied", direction="in", seq="", aid="")])
        ws, plan = self.plan(date(2026, 10, 19))
        stopped = {s["person_id"]: s["reason"] for s in plan["stopped"]}
        self.assertIn("someone at this account (b)", stopped["a"])       # replied 3 days before a's start
        self.assertNotIn("c", stopped)
        self.assertTrue(any("cannot stop an account" in p for p in ws.problems))

    def test_reply_logged_with_the_wrong_account_uses_the_book(self):
        self.setup([person("a", sequence="s1"), person("b", sequence="s1")],
                   [enroll("a", "2026-10-19")],
                   [act("1", "2026-10-16T11:00:00-04:00", "b", outcome="replied", direction="in", seq="", aid="A2")])
        ws, plan = self.plan(date(2026, 10, 19))
        self.assertIn("someone at this account (b)", {s["person_id"]: s["reason"] for s in plan["stopped"]}["a"])
        self.assertTrue(any("is at A1 in the book but the row says A2" in p for p in ws.problems))

    def test_old_reply_outside_the_lookback_does_not_stop_a_new_sequence(self):
        self.setup([person("a", sequence="s1"), person("b")], [enroll("a", "2026-10-19")],
                   [act("1", "2026-08-01T11:00:00-04:00", "b", outcome="replied", direction="in", seq="")])
        _, plan = self.plan(date(2026, 10, 19))
        self.assertNotIn("a", {s["person_id"] for s in plan["stopped"]})
        self.assertEqual(self.card(plan, "a")["step"], "1")

    def test_bounce_before_the_start_skips_email_steps_only(self):
        self.setup([person("a", sequence="s1", send_ok="no", followup_ok="yes")], [enroll("a", "2026-10-19")],
                   [act("1", "2026-10-01T10:00:00-04:00", "a", outcome="bounced", seq="")])
        _, plan = self.plan(date(2026, 10, 20))     # day 2: step 1 email skipped, step 2 call due today
        self.assertEqual(self.card(plan, "a")["channel"], "call")
        self.assertEqual([(s["step"], s["reason"]) for s in plan["skipped"]], [(1, "email bounced on 2026-10-01")])


class AllocationTests(Base):
    def test_callable_buyer_beats_a_linkedin_only_person_at_the_same_account(self):
        # The LinkedIn-only person scores higher (decision maker, inbound) but the account's one slot goes to the call.
        self.setup([person("li", phone="", call_ok="no", send_ok="no", role="decision_maker", tags="inbound",
                           title="Chief Financial Officer", notes="x"),
                    person("caller", role="influencer", title="AP Manager", last_touch_date="2026-08-01", notes="x")])
        _, plan = self.plan(date(2026, 10, 20))
        extras = [c for c in plan["cards"] if c["kind"] == "extra"]
        self.assertEqual([(c["person_id"], c["channel"]) for c in extras], [("caller", "call")])
        self.assertEqual(plan["dropped"].get("account already has an extra card today"), 1)

    def test_display_order_still_follows_the_blocks(self):
        self.cfg["daily"]["extras_per_account"] = 2
        (self.ws / "gtm.json").write_text(json.dumps(self.cfg))
        self.setup([person("li", phone="", call_ok="no", send_ok="no", notes="x"),
                    person("warm", tags="warm", notes="x")])
        _, plan = self.plan(date(2026, 10, 20))
        self.assertEqual([c["block"] for c in plan["cards"] if c["kind"] == "extra"], ["warm", "linkedin_only"])


class RerunTests(Base):
    def test_rerun_keeps_skip_reasons_and_your_own_columns(self):
        self.setup([person("a"), person("b", aid="A2", notes="x")], [enroll("a", "2026-10-14")])
        self.assertEqual(self.cli("--today", "2026-10-14")[0], 0)
        rows = read(self.ws / "plan/2026-10-14.csv")
        for r in rows:
            r["my_note"] = ""
            if r["person_id"] == "b":
                r["skip_reason"] = "out sick"
                r["my_note"] = "try Friday"
        write(self.ws / "plan/2026-10-14.csv", list(rows[0].keys()), rows)
        code, out = self.cli("--today", "2026-10-14")
        self.assertEqual(code, 0)
        self.assertIn("Kept 2 entries", out)
        again = {r["person_id"]: r for r in read(self.ws / "plan/2026-10-14.csv")}
        self.assertEqual((again["b"]["skip_reason"], again["b"]["my_note"]), ("out sick", "try Friday"))
        self.assertEqual(again["a"]["skip_reason"], "")
        self.assertIn("This is a rerun: 2 entries", (self.ws / "plan/2026-10-14.md").read_text())
        self.cli("--today", "2026-10-14", "--close")
        self.assertIn("Skipped with a reason: 1.", (self.ws / "plan/2026-10-14-close.md").read_text())

    def test_entry_whose_card_is_gone_is_listed_not_dropped(self):
        self.setup([person("a"), person("b", aid="A2", notes="x")], [enroll("a", "2026-10-14")])
        self.cli("--today", "2026-10-14")
        rows = read(self.ws / "plan/2026-10-14.csv")
        gone = dict(rows[0], card_id="2026-10-14-099", person_id="zz", name="Gone Person", kind="extra",
                    sequence="", step="", channel="call", status="ready", skip_reason="moved to a sequence card")
        write(self.ws / "plan/2026-10-14.csv", list(rows[0].keys()), rows + [gone])
        code, out = self.cli("--today", "2026-10-14")
        self.assertEqual(code, 0)
        self.assertIn("1 entry you wrote no longer matches a card", out)
        md = (self.ws / "plan/2026-10-14.md").read_text()
        self.assertIn("Entries kept from the last run that no longer match a card: 1.", md)
        self.assertIn("## Entries kept from the last run that no longer match a card", md)
        self.assertIn("2026-10-14-099 | Gone Person | extra call | skip_reason: moved to a sequence card", md)
        parked = read(self.ws / "plan/2026-10-14-unmatched.csv")
        self.assertEqual([r["person_id"] for r in parked], ["zz"])
        self.cli("--today", "2026-10-14")   # a second rerun still shows it: the parked file carries it
        self.assertIn("2026-10-14-099 | Gone Person", (self.ws / "plan/2026-10-14.md").read_text())
        self.assertFalse(any(r["person_id"] == "zz" for r in read(self.ws / "plan/2026-10-14.csv")))


class TemplateCopyTests(Base):
    def test_email_card_from_a_template_says_to_read_it_first(self):
        self.setup([person("p1")], [enroll("p1", "2026-10-14")])
        ws, plan = self.plan(date(2026, 10, 14))
        card = [c for c in plan["cards"] if c["kind"] == "sequence"][0]
        self.assertEqual(card["copy"], pd.TEMPLATE_NOTE)
        self.assertIn("- copy: filled from the template; read it before sending", pd.card_md(dict(card, card_id="x")))


class RunTests(Base):
    def test_nudge_fails_loudly_without_a_book(self):
        code, out = self.cli("--today", "2026-10-14", "--nudge")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAILED: book/people.csv is missing"))

    def test_close_accounts_for_every_card(self):
        self.setup([person("a"), person("b", aid="A2", notes="x")], [enroll("a", "2026-10-14")])
        self.assertEqual(self.cli("--today", "2026-10-14")[0], 0)
        rows = read(self.ws / "plan/2026-10-14.csv")
        write(self.ws / "log/activity.csv", LOG, [
            act("1", "2026-10-14T09:00:00-04:00", "a", "1", notes="we owe: pricing sheet by 2026-10-15")])
        for r in rows:
            if r["person_id"] == "b":
                r["skip_reason"] = "out sick"
        write(self.ws / "plan/2026-10-14.csv", list(rows[0].keys()), rows)
        code, out = self.cli("--today", "2026-10-14", "--close")
        self.assertEqual(code, 0)
        text = (self.ws / "plan/2026-10-14-close.md").read_text()
        self.assertIn("Done: 1. Skipped with a reason: 1.", text)
        self.assertIn("No record: 0.", text)
        self.assertIn("| we owe | pricing sheet | 2026-10-15 | a |", text)
        self.assertIn("Tomorrow's top 3 (2026-10-15)", text)

    def test_close_without_a_plan_is_an_error(self):
        self.setup([person("a")])
        code, out = self.cli("--today", "2026-10-14", "--close")
        self.assertEqual(code, 2)
        self.assertIn("no plan to close", out)

    def test_example_matches_expected_and_inputs_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "gtm"
            shutil.copytree(EXAMPLE, ws)
            inputs = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in ws.rglob("*") if p.is_file()}
            for argv in (["--today", "2026-10-20"], ["--today", "2026-10-20", "--close"]):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(pd.main(["--workspace", str(ws)] + argv), 0)
            for name in ("2026-10-20.md", "2026-10-20.csv", "2026-10-20-close.md"):
                self.assertEqual((ws / "plan" / name).read_text(), (EXAMPLE / "expected" / name).read_text(), name)
            for p, h in inputs.items():
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), h, p)
            written = {p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()} - \
                {p.relative_to(ws).as_posix() for p in inputs}
            self.assertTrue(all(w.startswith("plan/") for w in written), written)


if __name__ == "__main__":
    unittest.main()
