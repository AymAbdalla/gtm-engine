"""Rules for aym-gtm play-build: eligibility funnel, seats, caps, dates, overrides and play types."""
import csv
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
SKILL = ROOT / "plugins/aym-gtm/skills/play-build"
spec = importlib.util.spec_from_file_location("build_play", SKILL / "scripts/build_play.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)
EXAMPLE = SKILL / "assets/example"

PEOPLE = ["person_id", "account_id", "first_name", "last_name", "title", "email", "phone", "status",
          "last_touch_date", "sequence", "tags", "persona", "lane", "role", "send_ok", "send_block_reason",
          "call_ok", "call_block_reason"]
ACCTS = ["account_id", "name", "tier", "relationship", "status", "owner", "strategy", "tags", "past_value"]
ACT = ["activity_id", "timestamp", "person_id", "account_id", "channel", "direction", "sequence", "step",
       "play_id", "angle", "opener", "outcome", "notes", "source"]
TODAY = date(2026, 10, 20)  # a Tuesday


def write(path, cols, rows, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def person(pid, aid, role="decision_maker", **kw):
    base = {"person_id": pid, "account_id": aid, "first_name": pid.title(), "last_name": "Test",
            "title": "CFO", "status": "active", "persona": "cfo", "lane": "finance", "role": role,
            "send_ok": "yes", "call_ok": "yes", "phone": "+1-312-555-0100"}
    base.update(kw)
    return base


def account(aid, **kw):
    base = {"account_id": aid, "name": f"Acct {aid}", "tier": "P2", "status": "active", "owner": "you",
            "strategy": "signal"}
    base.update(kw)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "gtm"
        (self.ws / "book").mkdir(parents=True)
        (self.ws / "gtm.json").write_text(json.dumps({"stop_statuses": ["do_not_contact", "left", "booked"],
                                                      "dnc_tags": ["opted_out"], "left_tags": ["moved"]}))
        seqs = {"sequences": [{"id": "seq-a", "variables": {"first_name": {}, "company": {}, "trigger_fact": {}},
                               "steps": [{"day": 1}, {"day": 3}, {"day": 5}]}]}
        (self.ws / "outreach").mkdir()
        (self.ws / "outreach/sequences.json").write_text(json.dumps(seqs))

    def tearDown(self):
        self.tmp.cleanup()

    def book(self, people, accounts):
        write(self.ws / "book/people.csv", PEOPLE, people)
        write(self.ws / "book/accounts.csv", ACCTS, accounts)

    def signals(self, rows):
        cols = ["account_id", "name", "score", "top_type", "playable", "why_not", "why_now", "source_url",
                "event_date", "seat", "check"]
        write(self.ws / "signals/scored.csv", cols, rows)

    def play(self, **kw):
        p = {"id": "p1", "type": "signal", "sequence": "seq-a", "start": "2026-10-21", "channel": "email",
             "daily_cap": 5}
        p.update(kw)
        path = self.ws / "plays" / p["id"] / "play.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(p))
        return path

    def run_play(self, path, today=TODAY):
        return bp.build(self.ws, path, today)

    def enroll(self, pid="p1"):
        return {r["person_id"]: r for r in read(self.ws / "plays" / pid / "enroll.csv")}

    def report(self, pid="p1"):
        return (self.ws / "plays" / pid / "report.md").read_text()


def sig(aid, score="5", top="funding", seat="decision maker", **kw):
    row = {"account_id": aid, "name": f"Acct {aid}", "score": score, "top_type": top, "playable": "yes",
           "why_now": f"Closed a round (source dated 2026-10-01).", "source_url": "https://news.example/x",
           "event_date": "2026-10-01", "seat": seat}
    row.update(kw)
    return row


class MissingSettingsTests(Base):
    """D1 (Oct 22): a play with no channel, start, daily cap or sequence writes no list."""

    def test_missing_settings_stop_the_run_and_name_every_key(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        path = self.play()
        data = json.loads(path.read_text())
        for key in ("channel", "daily_cap"):
            data.pop(key)
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError) as ctx:
            self.run_play(path)
        self.assertIn("channel", str(ctx.exception))
        self.assertIn("daily_cap", str(ctx.exception))
        self.assertFalse((self.ws / "plays/p1/enroll.csv").exists())


class HoldoutTests(Base):
    """An optional holdout keeps a stable share of eligible accounts untouched for comparison."""

    def setUp(self):
        super().setUp()
        self.accts = [f"A{i:02d}" for i in range(1, 21)]
        self.book([person(f"p{a}", a) for a in self.accts], [account(a, strategy="priority") for a in self.accts])

    def expected_holdout(self, share):
        import hashlib
        return {a for a in self.accts
                if int(hashlib.sha256(f"p1:{a}".encode()).hexdigest(), 16) / 16 ** 64 < share}

    def test_holdout_share_is_stable_and_counted(self):
        path = self.play(type="blitz", accounts=self.accts, channel="any", daily_cap=20, holdout_share=0.3)
        self.run_play(path)
        rows = self.enroll()
        held = {r["account_id"] for r in rows.values() if r["drop_reason"].startswith("holdout")}
        self.assertEqual(held, self.expected_holdout(0.3))
        self.assertTrue(0 < len(held) < len(self.accts))
        funnel = (self.ws / "plays/p1/funnel.md").read_text()
        self.assertIn("holdout", funnel)
        self.assertIn("The counts add up", funnel)
        self.run_play(path)
        again = {r["account_id"] for r in self.enroll().values() if r["drop_reason"].startswith("holdout")}
        self.assertEqual(again, held)

    def test_holdout_counts_the_seat_that_would_have_been_touched(self):
        # Oct 22 check finding: every eligible person at a held-out account counted as holdout,
        # while the worked side counted one seat per account. Both sides must count seats.
        people = [person(f"{a}-{n}", a, role=r) for a in self.accts
                  for n, r in (("dm", "decision_maker"), ("ch", "champion"), ("in", "influencer"))]
        self.book(people, [account(a, strategy="priority") for a in self.accts])
        self.run_play(self.play(type="blitz", accounts=self.accts, channel="any", daily_cap=60,
                                holdout_share=0.3, per_account_cap=1))
        rows = self.enroll()
        held = self.expected_holdout(0.3)
        self.assertTrue(held)
        for a in held:
            at = [r for r in rows.values() if r["account_id"] == a]
            self.assertEqual([r["person_id"] for r in at if r["drop_reason"].startswith("holdout")], [f"{a}-dm"], a)
        worked = [r for r in rows.values() if r["rank"]]
        self.assertEqual(len(worked), len(self.accts) - len(held))

    def test_an_added_person_at_a_held_out_account_stays_out(self):
        held = sorted(self.expected_holdout(0.3))
        self.book([person(f"p{a}", a) for a in self.accts] + [person("extra", held[0], role="influencer")],
                  [account(a, strategy="priority") for a in self.accts])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason", "date"],
              [{"person_id": "extra", "action": "add", "reason": "met at a dinner"}])
        self.run_play(self.play(type="blitz", accounts=self.accts, channel="any", daily_cap=20, holdout_share=0.3))
        self.assertFalse(self.enroll()["extra"]["rank"])
        self.assertIn("extra is at a held-out account", self.report())

    def test_no_holdout_by_default(self):
        self.run_play(self.play(type="blitz", accounts=self.accts, channel="any", daily_cap=20))
        self.assertFalse(any(r["drop_reason"].startswith("holdout") for r in self.enroll().values()))


class LiveDealTests(Base):
    """Oct 22 review probe: the book said re-engage, but the account had an open deal."""

    def test_account_status_blocks_outbound_whatever_the_strategy(self):
        self.book([person("a", "A1"), person("h", "A2"), person("x", "A3"), person("ok", "A4")],
                  [account("A1", status="live_deal", strategy="re-engage", owner=""),
                   account("A2", status="hold", strategy="automated", owner=""),
                   account("A3", status="archived", strategy="priority", owner=""),
                   account("A4", strategy="priority", owner="")])
        self.run_play(self.play(type="blitz", accounts=["A1", "A2", "A3", "A4"], channel="any"))
        rows = self.enroll()
        self.assertIn("live_deal", rows["a"]["drop_reason"])
        self.assertIn("hold", rows["h"]["drop_reason"])
        self.assertIn("archived", rows["x"]["drop_reason"])
        self.assertEqual(rows["ok"]["drop_reason"], "")


class FunnelTests(Base):
    def test_every_drop_counted_and_funnel_adds_up(self):
        self.book([person("a", "A1"), person("b", "A2", status="do_not_contact"),
                   person("c", "A3"), person("d", "A4"), person("e", "A5", send_ok="no",
                                                             send_block_reason="catch-all domain")],
                  [account("A1"), account("A2"), account("A3", strategy="live"),
                   account("A4", owner="jordan"), account("A5")])
        self.signals([sig("A1"), sig("A2"), sig("A3"), sig("A4"), sig("A5")])
        res = self.run_play(self.play())
        rows = self.enroll()
        self.assertEqual(res["proposed"], 1)
        self.assertEqual(rows["b"]["drop_reason"], "status do_not_contact")
        self.assertEqual(rows["c"]["drop_reason"], "account strategy live")
        self.assertEqual(rows["d"]["drop_reason"], "owned by jordan")
        self.assertEqual(rows["e"]["drop_reason"], "email gate: catch-all domain")
        funnel = (self.ws / "plays/p1/funnel.md").read_text()
        self.assertIn("| 0 | Everyone in the book | | 5 |", funnel)
        self.assertIn("Proposed: 1.", funnel)
        self.assertIn("Check: 5 in the book minus 4 removed", funnel)
        self.assertIn("The counts add up.", funnel)

    def test_funnel_check_flags_counts_that_do_not_add_up(self):
        f = bp.Funnel(3)
        f.step("rule", [("a", "x")])
        out = self.ws / "funnel.md"
        bp.write_funnel(out, {"id": "p1", "type": "signal"}, f, 1)
        self.assertIn("Check FAILED: 3 minus 1 is 2, not 1.", out.read_text())

    def test_out_of_scope_people_are_counted_not_listed(self):
        self.book([person("a", "A1"), person("z", "A9")], [account("A1"), account("A9")])
        self.signals([sig("A1"), sig("A9", playable="no", why_not="only context signals")])
        self.run_play(self.play())
        self.assertNotIn("z", self.enroll())
        self.assertIn("signal not playable: only context signals", (self.ws / "plays/p1/funnel.md").read_text())

    def test_already_in_sequence_gets_reply_suggestion(self):
        self.book([person("a", "A1", sequence="seq-old", send_ok="no",
                          send_block_reason="already in sequence seq-old")], [account("A1")])
        self.signals([sig("A1")])
        self.run_play(self.play())
        self.assertIn("reply in that thread", self.enroll()["a"]["drop_reason"])
        self.assertIn("reply in that thread instead of a new sequence", self.report())

    def test_one_live_play_per_person(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        write(self.ws / "plays/other/enroll.csv", bp.ENROLL_COLS,
              [{"play_id": "other", "person_id": "a", "account_id": "A1", "approved": "yes"}])
        self.run_play(self.play())
        self.assertIn("approved in play other", self.enroll()["a"]["drop_reason"])

    def test_left_and_optout_tags_block(self):
        self.book([person("a", "A1", tags="moved"), person("b", "A1", tags="opted_out")], [account("A1")])
        self.signals([sig("A1")])
        self.run_play(self.play(per_account_cap=2))
        rows = self.enroll()
        self.assertIn("may have left", rows["a"]["drop_reason"])
        self.assertIn("opted out", rows["b"]["drop_reason"])

    def test_corrupt_future_activity_is_ignored_and_reported(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        write(self.ws / "log/activity.csv", ACT, [{"activity_id": "x", "timestamp": "2026-12-01T09:00:00-05:00",
                                                   "person_id": "a", "account_id": "A1", "direction": "out",
                                                   "outcome": "sent"}])
        res = self.run_play(self.play())
        self.assertEqual(res["proposed"], 1)  # the future touch does not count as recent
        self.assertIn("ignored as corrupt", self.report())


class SeatTests(Base):
    def test_named_new_leader_gets_the_seat(self):
        self.book([person("cfo", "A1", first_name="Dana", last_name="Whitfield"),
                   person("vp", "A1", first_name="Hollis", last_name="Brandt")], [account("A1")])
        self.signals([sig("A1", top="new_leader", seat="Dana Whitfield, Chief Financial Officer (the named new leader)")])
        self.run_play(self.play(per_account_cap=2))
        rows = self.enroll()
        self.assertEqual(rows["cfo"]["rank"], "1")
        self.assertEqual(rows["vp"]["drop_reason"], "not the seat this signal points to")

    def test_named_leader_reads_the_fact_about_themselves(self):
        self.book([person("cfo", "A1", first_name="Dana", last_name="Whitfield", title="CFO"),
                   person("cfo2", "A2", first_name="Jo", last_name="Lin")],
                  [account("A1", name="Brightmill Manufacturing"), account("A2", name="Acme")])
        self.signals([sig("A1", top="new_leader", seat="Dana Whitfield, Chief Financial Officer (the named new leader)",
                          why_now="Named Dana Whitfield as Chief Financial Officer (source dated 2026-09-28)."),
                      sig("A2", top="new_leader", seat="Jo Lin, CFO (the named new leader)",
                          why_now="Jo Lin joined Acme as CFO (source dated 2026-09-28).")])
        self.run_play(self.play(daily_cap=5))
        facts = {pid: json.loads(r["variables"])["trigger_fact"] for pid, r in self.enroll().items()}
        # Written to the leader, so "you", never their own name in the third person.
        self.assertEqual(facts["cfo"], "Brightmill Manufacturing named you Chief Financial Officer")
        self.assertEqual(facts["cfo2"], "you joined Acme as CFO")
        self.assertNotIn("Whitfield", facts["cfo"])

    def test_named_leader_fact_to_confirm_is_also_second_person(self):
        self.book([person("cfo", "A1", first_name="Dana", last_name="Whitfield")],
                  [account("A1", name="Brightmill Manufacturing")])
        self.signals([sig("A1", top="new_leader", seat="Dana Whitfield, CFO (the named new leader)",
                          why_now="Named Dana Whitfield as CFO (source dated 2026-09-28).",
                          check="source names Brightmill Foods: confirm it is the same company")])
        self.run_play(self.play())
        variables = json.loads(self.enroll()["cfo"]["variables"])
        self.assertEqual(variables["trigger_fact"], "")
        self.assertEqual(variables["trigger_fact_to_confirm"], "Brightmill Manufacturing named you CFO")

    def test_trigger_fact_reads_after_i_saw(self):
        self.book([person("a", "A1"), person("b", "A2"), person("c", "A3")],
                  [account("A1", name="Northpine Logistics"), account("A2", name="Acme"),
                   account("A3", name="Acme Two")])
        self.signals([sig("A1", why_now="Posted an opening for an Accounts Payable Manager (source dated 2026-10-05)."),
                      sig("A2", why_now="Acme raised a Series B (source dated 2026-10-01)."),
                      sig("A3", why_now="CFO Jo Lin joined in September (source dated 2026-10-01).")])
        self.run_play(self.play(daily_cap=5))
        facts = {pid: json.loads(r["variables"])["trigger_fact"] for pid, r in self.enroll().items()}
        self.assertEqual(facts["a"], "Northpine Logistics posted an opening for an Accounts Payable Manager")
        self.assertEqual(facts["b"], "Acme raised a Series B")           # already starts with the name
        self.assertEqual(facts["c"], "Acme Two CFO Jo Lin joined in September")   # acronyms keep their case
        self.assertEqual(json.loads(self.enroll()["a"]["variables"])["source_url"], "https://news.example/x")
        self.assertIn("open each source link before the first touch (a, b, c quote a dated fact)", self.report())

    def test_missing_named_leader_falls_back_and_is_reported(self):
        self.book([person("vp", "A1", first_name="Hollis", last_name="Brandt")], [account("A1")])
        self.signals([sig("A1", top="new_leader", seat="Dana Whitfield, CFO (the named new leader)",
                          why_now="Named Dana Whitfield as CFO (source dated 2026-09-28).")])
        self.run_play(self.play())
        row = self.enroll()["vp"]
        self.assertEqual(row["rank"], "1")
        self.assertIn("plain first touch", row["seat"])
        # The fact is about Dana, not Hollis: it is never put in Hollis's first line.
        self.assertEqual(json.loads(row["variables"])["trigger_fact"], "")
        self.assertIn("named person in the signal is not workable", self.report())
        self.assertIn("variable `trigger_fact` is blank for vp", self.report())

    def test_unconfirmed_fact_is_never_quoted(self):
        self.book([person("a", "A1")], [account("A1", name="Brightmill Manufacturing")])
        self.signals([sig("A1", why_now="Closed a round (source dated 2026-10-01).",
                          check="source names Brightmill Foods; your account is Brightmill Manufacturing on "
                                "the same domain: confirm it is the same company")])
        self.run_play(self.play())
        variables = json.loads(self.enroll()["a"]["variables"])
        self.assertEqual(variables["trigger_fact"], "")
        self.assertEqual(variables["trigger_fact_to_confirm"], "Brightmill Manufacturing closed a round")
        self.assertEqual(variables["source_url"], "https://news.example/x")
        self.assertIn("needs human: confirm the fact", self.report())
        self.assertIn("source names Brightmill Foods", self.report())

    def test_leader_gap_never_picks_the_person_who_left(self):
        self.book([person("gone", "A1", first_name="Marcus", last_name="Lee"),
                   person("stay", "A1", first_name="Ana", last_name="Diaz", role="champion")], [account("A1")])
        self.signals([sig("A1", top="leader_gap", seat="the most senior remaining leader; not Marcus Lee")])
        self.run_play(self.play())
        rows = self.enroll()
        self.assertEqual(rows["stay"]["rank"], "1")
        self.assertNotEqual(rows["gone"]["rank"], "1")

    def test_intent_is_timing_only(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1", top="topic_intent", why_now="Timing only: research interest (do not mention).")])
        self.run_play(self.play())
        variables = json.loads(self.enroll()["a"]["variables"])
        self.assertEqual(variables["trigger_fact"], "")
        self.assertIn("never mention it", self.report())

    def test_hiring_prefers_the_champion(self):
        self.book([person("dm", "A1"), person("ch", "A1", role="champion", persona="controller")], [account("A1")])
        self.signals([sig("A1", top="hiring", seat="the likely manager of the open role")])
        self.run_play(self.play())
        self.assertEqual(self.enroll()["ch"]["rank"], "1")


class CalendarTests(Base):
    def test_daily_cap_and_one_per_account_per_day(self):
        people = [person(f"x{i}", f"A{i % 3}", role="decision_maker") for i in range(6)]
        self.book(people, [account("A0"), account("A1"), account("A2")])
        self.signals([sig("A0", score="9"), sig("A1", score="8"), sig("A2", score="7")])
        self.run_play(self.play(daily_cap=2, per_account_cap=2))
        rows = [r for r in self.enroll().values() if r["rank"]]
        by_day = {}
        for r in rows:
            by_day.setdefault(r["sequence_start"], []).append(r["account_id"])
        for accts in by_day.values():
            self.assertLessEqual(len(accts), 2)
            self.assertEqual(len(accts), len(set(accts)))
        self.assertEqual(min(by_day), "2026-10-21")
        self.assertNotIn("2026-10-24", by_day)  # Saturday skipped

    def test_end_date_limits_capacity(self):
        people = [person(f"x{i}", f"A{i}") for i in range(4)]
        self.book(people, [account(f"A{i}") for i in range(4)])
        self.signals([sig(f"A{i}") for i in range(4)])
        self.run_play(self.play(daily_cap=1, end="2026-10-22"))
        rows = self.enroll()
        self.assertEqual(sum(1 for r in rows.values() if r["rank"]), 2)
        self.assertTrue(any("no start date left before 2026-10-22" in r["drop_reason"] for r in rows.values()))

    def test_approved_rows_keep_dates_and_answers(self):
        self.book([person("a", "A1"), person("b", "A2")], [account("A1"), account("A2")])
        self.signals([sig("A1", score="9"), sig("A2", score="8")])
        path = self.play()
        self.run_play(path)
        rows = read(self.ws / "plays/p1/enroll.csv")
        for r in rows:
            if r["person_id"] == "b":
                r["approved"] = "yes"
                r["sequence_start"] = "2026-10-27"
        write(self.ws / "plays/p1/enroll.csv", bp.ENROLL_COLS, rows)
        self.run_play(path, date(2026, 10, 21))
        b = self.enroll()["b"]
        self.assertEqual((b["approved"], b["sequence_start"]), ("yes", "2026-10-27"))

    def test_approved_then_blocked_is_flagged(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        path = self.play()
        self.run_play(path)
        rows = read(self.ws / "plays/p1/enroll.csv")
        rows[0]["approved"] = "yes"
        write(self.ws / "plays/p1/enroll.csv", bp.ENROLL_COLS, rows)
        self.book([person("a", "A1", status="do_not_contact")], [account("A1")])
        self.run_play(path)
        self.assertIn("was approved, now blocked", self.enroll()["a"]["drop_reason"])
        self.assertIn("was approved but is now blocked", self.report())


class RerunTests(Base):
    def edit(self, fn, pid="p1"):
        path = self.ws / "plays" / pid / "enroll.csv"
        rows = read(path)
        for r in rows:
            fn(r)
        write(path, bp.ENROLL_COLS, rows)

    def test_rerun_keeps_typed_variables(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        seqs = {"sequences": [{"id": "seq-a", "variables": {"first_name": {}, "trigger_fact": {}, "last_topic": {}},
                               "steps": [{"day": 1}, {"day": 3}]}]}
        (self.ws / "outreach/sequences.json").write_text(json.dumps(seqs))
        path = self.play()
        self.run_play(path)

        def fill(r):
            if r["rank"]:
                v = json.loads(r["variables"])
                v["last_topic"] = "month-end close"
                v["first_name"] = "Danny"   # an edit to a value the script wrote
                r["variables"] = json.dumps(v, sort_keys=True)
                r["approved"] = "yes"
        self.edit(fill)
        self.run_play(path, date(2026, 10, 20))
        row = self.enroll()["a"]
        variables = json.loads(row["variables"])
        self.assertEqual((variables["last_topic"], variables["first_name"]), ("month-end close", "Danny"))
        self.assertEqual(row["approved"], "yes")
        self.assertNotIn("last_topic", self.report())

    def test_approved_row_keeps_its_seat_when_a_better_seat_frees_up(self):
        touch = {"activity_id": "t", "timestamp": "2026-10-14T10:00:00-04:00", "person_id": "ch",
                 "account_id": "A1", "direction": "out", "outcome": "voicemail"}
        write(self.ws / "log/activity.csv", ACT, [touch])
        self.book([person("dm", "A1"), person("ch", "A1", role="champion", persona="controller")], [account("A1")])
        self.signals([sig("A1", top="hiring", seat="the likely manager of the open role")])
        path = self.play()
        self.run_play(path)
        self.assertEqual(self.enroll()["dm"]["rank"], "1")    # the champion was touched recently
        self.edit(lambda r: r.update(approved="yes") if r["rank"] else None)
        # Nine days later the champion is free again, and dm's sequence has started.
        self.run_play(path, date(2026, 10, 29))
        rows = self.enroll()
        self.assertEqual((rows["dm"]["sequence_start"], rows["dm"]["approved"]), ("2026-10-21", "yes"))
        self.assertEqual(rows["ch"]["drop_reason"], "account cap: 1 per account")
        self.assertNotIn("now blocked", self.report())

    def test_running_sequence_survives_its_signal_expiring(self):
        self.book([person("a", "A1"), person("b", "A1", role="champion")], [account("A1")])
        self.signals([sig("A1")])
        path = self.play()
        self.run_play(path)
        self.edit(lambda r: r.update(approved="yes") if r["rank"] else None)
        self.signals([sig("A1", playable="no", why_not="signal expired")])
        self.run_play(path, date(2026, 10, 23))
        rows = self.enroll()
        self.assertEqual((rows["a"]["approved"], rows["a"]["sequence_start"]), ("yes", "2026-10-21"))
        self.assertNotIn("b", rows)   # the rest of the account is out of scope again

    def test_blocked_flag_stays_until_you_clear_approved(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        path = self.play()
        self.run_play(path)
        self.edit(lambda r: r.update(approved="yes"))
        self.book([person("a", "A1", status="do_not_contact")], [account("A1")])
        for day in (20, 21):
            self.run_play(path, date(2026, 10, day))
            row = self.enroll()["a"]
            self.assertEqual(row["approved"], "yes")
            self.assertTrue(row["drop_reason"].startswith("was approved, now blocked"))
            self.assertIn("Clear `approved`", self.report())
        self.edit(lambda r: r.update(approved=""))
        self.run_play(path, date(2026, 10, 22))
        self.assertEqual(self.enroll()["a"]["drop_reason"], "status do_not_contact")
        self.assertNotIn("now blocked", self.report())


class StopTests(Base):
    def test_log_stop_outcome_and_open_conversation(self):
        self.book([person("opt", "A1"), person("talk", "A2"), person("old", "A3"), person("bnc", "A4")],
                  [account(f"A{i}") for i in range(1, 5)])
        self.signals([sig(f"A{i}") for i in range(1, 5)])
        acts = [{"activity_id": "1", "timestamp": "2026-03-01T09:00:00-05:00", "person_id": "opt",
                 "account_id": "A1", "direction": "in", "outcome": "opt_out"},
                {"activity_id": "2", "timestamp": "2026-10-10T09:00:00-04:00", "person_id": "talk",
                 "account_id": "A2", "direction": "in", "outcome": "replied"},
                {"activity_id": "3", "timestamp": "2026-06-01T09:00:00-04:00", "person_id": "old",
                 "account_id": "A3", "direction": "in", "outcome": "replied"},
                {"activity_id": "4", "timestamp": "2026-05-01T09:00:00-04:00", "person_id": "bnc",
                 "account_id": "A4", "direction": "out", "channel": "email", "outcome": "bounced"}]
        write(self.ws / "log/activity.csv", ACT, acts)
        self.run_play(self.play(daily_cap=5))
        rows = self.enroll()
        self.assertEqual(rows["opt"]["drop_reason"], "log outcome opt_out on 2026-03-01")
        self.assertIn("in a live conversation since 2026-10-10", rows["talk"]["drop_reason"])
        self.assertTrue(rows["old"]["rank"])            # a reply months ago is not an open conversation
        self.assertEqual(rows["bnc"]["drop_reason"], "log outcome bounced on 2026-05-01")
        # A bounce blocks email only.
        self.run_play(self.play(id="p2", channel="call", daily_cap=5))
        self.assertTrue(self.enroll("p2")["bnc"]["rank"])

    def test_other_play_stops_holding_after_its_sequence_ends(self):
        self.book([person("a", "A1"), person("b", "A2")], [account("A1"), account("A2")])
        self.signals([sig("A1"), sig("A2")])
        (self.ws / "plays/old").mkdir(parents=True)
        (self.ws / "plays/old/play.json").write_text(json.dumps({"id": "old", "type": "blitz", "sequence": "seq-a",
                                                               "start": "2026-09-01"}))
        write(self.ws / "plays/old/enroll.csv", bp.ENROLL_COLS, [
            {"play_id": "old", "person_id": "a", "account_id": "A1", "sequence_start": "2026-09-01",
             "approved": "yes"},     # 5-day sequence, ended in September
            {"play_id": "old", "person_id": "b", "account_id": "A2", "sequence_start": "2026-10-19",
             "approved": "yes"}])    # still running
        self.run_play(self.play(daily_cap=5))
        rows = self.enroll()
        self.assertTrue(rows["a"]["rank"])
        self.assertIn("approved in play old", rows["b"]["drop_reason"])


class OverrideTests(Base):
    def test_add_comes_on_top_of_cap_and_remove_drops(self):
        self.book([person("a", "A1"), person("b", "A1", role="influencer"), person("c", "A2")],
                  [account("A1"), account("A2")])
        self.signals([sig("A1"), sig("A2")])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason", "date"],
              [{"person_id": "b", "action": "add", "reason": "asked for a demo"},
               {"person_id": "c", "action": "remove", "reason": "too junior"}])
        self.run_play(self.play())
        rows = self.enroll()
        self.assertTrue(rows["a"]["rank"] and rows["b"]["rank"])
        self.assertIn("added by you", rows["b"]["seat"])
        self.assertEqual(rows["c"]["drop_reason"], "removed by you: too junior")

    def test_adds_count_each_person_and_respect_owner_and_live(self):
        self.book([person("a", "A1"), person("b", "A2"), person("c", "A3"), person("d", "A4")],
                  [account("A1"), account("A2"), account("A3", owner="jordan"), account("A4", strategy="live")])
        self.signals([sig(f"A{i}") for i in range(1, 5)])
        # a and b were called last week, so the recent-touch rule drops them; you add them back.
        write(self.ws / "log/activity.csv", ACT, [
            {"activity_id": p, "timestamp": "2026-10-15T10:00:00-04:00", "person_id": p,
             "account_id": a, "direction": "out", "outcome": "voicemail"} for p, a in (("a", "A1"), ("b", "A2"))])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason", "date"],
              [{"person_id": p, "action": "add", "reason": "met at conference"} for p in ("a", "b", "c", "d")])
        self.run_play(self.play(daily_cap=5))
        funnel = (self.ws / "plays/p1/funnel.md").read_text()
        self.assertIn("| +2 added |", funnel)
        self.assertIn("- 2: added: met at conference", funnel)
        rows = self.enroll()
        self.assertTrue(rows["a"]["rank"] and rows["b"]["rank"])
        self.assertIn("owned by jordan", self.report())
        self.assertIn("account strategy live", self.report())

    def test_add_for_a_live_conversation_is_flagged_and_gets_no_cold_line(self):
        self.book([person("a", "A1"), person("b", "A1", role="influencer"), person("c", "A2", role="influencer")],
                  [account("A1"), account("A2")])
        self.signals([sig("A1"), sig("A2")])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason", "date"],
              [{"person_id": "b", "action": "add", "reason": "AP lead asked for a demo at a webinar"},
               {"person_id": "c", "action": "add", "reason": "met at conference"}])
        self.run_play(self.play(daily_cap=5))
        rows = self.enroll()
        self.assertTrue(rows["b"]["rank"])                       # still proposed
        self.assertEqual(json.loads(rows["b"]["variables"])["trigger_fact"], "")
        self.assertEqual(json.loads(rows["c"]["variables"])["trigger_fact"], "Acct A2 closed a round")
        report = self.report()
        self.assertIn("B Test (b): reply by hand first: the override reason suggests a live conversation", report)
        self.assertNotIn("(c): reply by hand first", report)

    def test_live_conversation_words_come_from_config(self):
        self.book([person("a", "A1"), person("b", "A1", role="influencer")], [account("A1")])
        self.signals([sig("A1")])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason"],
              [{"person_id": "b", "action": "add", "reason": "texted me back"}])
        cfg = json.loads((self.ws / "gtm.json").read_text())
        cfg["play"] = {"override_conversation_words": ["texted"]}
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        self.run_play(self.play())
        self.assertEqual(json.loads(self.enroll()["b"]["variables"])["trigger_fact"], "")
        self.assertIn("reply by hand first", self.report())

    def test_conversation_word_matching(self):
        words = bp.DEFAULT_PLAY["override_conversation_words"]
        for reason in ("asked for a demo", "Replies fast", "wants a call back", "introduced by Sam",
                       "requests pricing", "had a meeting"):
            self.assertTrue(bp.conversation_word(reason, words), reason)
        for reason in ("met at conference", "too junior", "strong fit", ""):
            self.assertEqual(bp.conversation_word(reason, words), "", reason)

    def test_add_cannot_beat_a_hard_rule(self):
        self.book([person("a", "A1", status="do_not_contact")], [account("A1")])
        self.signals([sig("A1")])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason"],
              [{"person_id": "a", "action": "add", "reason": "met at a dinner"}])
        self.run_play(self.play())
        self.assertFalse(self.enroll()["a"]["rank"])
        self.assertIn("a hard rule blocks them", self.report())

    def test_repeated_reason_becomes_a_rule_idea(self):
        self.book([person("a", "A1"), person("b", "A2")], [account("A1"), account("A2")])
        self.signals([sig("A1"), sig("A2")])
        write(self.ws / "plays/p1/overrides.csv", ["person_id", "action", "reason"],
              [{"person_id": "a", "action": "remove", "reason": "Too junior"},
               {"person_id": "b", "action": "remove", "reason": "too junior"}])
        self.run_play(self.play())
        self.assertIn("Rule ideas from your overrides", self.report())


class TypeTests(Base):
    def events(self, status="confirmed", day="2026-11-12"):
        write(self.ws / "input/events.csv", ["event_id", "name", "date", "city", "area_codes", "topic", "personas", "status"],
              [{"event_id": "E1", "name": "Breakfast", "date": day, "city": "Chicago", "area_codes": "312;773",
                "personas": "cfo", "status": status}])

    def test_event_area_codes_and_cutoff(self):
        self.book([person("near", "A1"), person("far", "A2", phone="+1-206-555-0100")],
                  [account("A1"), account("A2")])
        self.events()
        path = self.play(id="ev", type="event", event={"event_id": "E1"})
        self.run_play(path)
        rows = self.enroll("ev")
        self.assertEqual(rows["near"]["rank"], "1")
        self.assertEqual(rows["far"]["drop_reason"], "not near Chicago")
        # 3-step sequence over 5 days must finish 2 business days before 2026-11-12
        self.assertIn("Last possible start: 2026-11-04", self.report("ev"))

    def test_tentative_event_proposes_nobody(self):
        self.book([person("near", "A1")], [account("A1")])
        self.events(status="tentative")
        res = self.run_play(self.play(id="ev", type="event", event={"event_id": "E1"}))
        self.assertEqual(res["proposed"], 0)
        self.assertEqual(self.enroll("ev")["near"]["drop_reason"], "event is tentative: wait")

    def test_reactivation_rhythm_and_past_value(self):
        self.book([person("never", "A0"), person("quiet", "A1"), person("busy", "A2"), person("big", "A3")],
                  [account("A0"), account("A1", past_value="10,000"), account("A2"),
                   account("A3", past_value="50,000", tags="lost_deal")])
        acts = []
        for i, d in enumerate(["2026-05-01", "2026-05-31", "2026-06-30"]):
            acts.append({"activity_id": f"q{i}", "timestamp": d + "T09:00:00-04:00", "person_id": "quiet",
                         "account_id": "A1", "direction": "out", "outcome": "sent"})
        acts.append({"activity_id": "b1", "timestamp": "2026-10-01T09:00:00-04:00", "person_id": "busy",
                     "account_id": "A2", "direction": "out", "outcome": "sent"})
        acts.append({"activity_id": "g1", "timestamp": "2026-09-30T09:00:00-04:00", "person_id": "big",
                     "account_id": "A3", "direction": "out", "outcome": "sent"})
        write(self.ws / "log/activity.csv", ACT, acts)
        self.run_play(self.play(id="rb", type="reactivation", channel="any"))
        rows = self.enroll("rb")
        self.assertNotIn("never", rows)               # never touched: out of scope
        self.assertNotIn("busy", rows)                # not quiet yet
        self.assertEqual(rows["big"]["rank"], "1")    # tagged lost_deal, highest past value
        self.assertEqual(rows["quiet"]["rank"], "2")  # quiet past its monthly rhythm
        self.assertIn("names the gap and does not pitch", self.report("rb"))

    def test_reactivation_skips_people_touched_recently_even_when_tagged(self):
        self.book([person("big", "A1"), person("other", "A1", role="champion", persona="controller")],
                  [account("A1", tags="lost_deal", past_value="50,000")])
        write(self.ws / "log/activity.csv", ACT, [
            {"activity_id": "1", "timestamp": "2026-03-01T09:00:00-05:00", "person_id": "other",
             "account_id": "A1", "direction": "out", "outcome": "sent"},
            {"activity_id": "2", "timestamp": "2026-10-17T09:00:00-04:00", "person_id": "big",
             "account_id": "A1", "direction": "out", "outcome": "connected"}])
        self.run_play(self.play(id="rb", type="reactivation", channel="any"))
        rows = self.enroll("rb")
        self.assertIn("touched 2026-10-17, within 14 days", rows["big"]["drop_reason"])
        self.assertTrue(rows["other"]["rank"])

    def test_multithread_adds_only_new_lanes(self):
        self.book([person("eng", "A1"), person("same", "A1", role="champion"),
                   person("tech", "A1", role="technical_gatekeeper", lane="tech", persona="it_director")],
                  [account("A1")])
        write(self.ws / "log/activity.csv", ACT, [{"activity_id": "r", "timestamp": "2026-10-01T09:00:00-04:00",
                                                   "person_id": "eng", "account_id": "A1", "direction": "in",
                                                   "outcome": "replied"}])
        self.run_play(self.play(id="mt", type="multithread"))
        rows = self.enroll("mt")
        self.assertEqual(rows["tech"]["rank"], "1")
        self.assertEqual(rows["same"]["drop_reason"], "lane already engaged")

    def test_blitz_follows_listed_order(self):
        self.book([person("a", "A1"), person("b", "A2"), person("c", "A3")],
                  [account("A1"), account("A2"), account("A3")])
        self.run_play(self.play(id="bz", type="blitz", accounts=["A3", "A1", "NOPE"], daily_cap=1))
        rows = self.enroll("bz")
        self.assertEqual((rows["c"]["rank"], rows["a"]["rank"]), ("1", "2"))
        self.assertNotIn("b", rows)
        self.assertIn("NOPE", self.report("bz"))


class StateAndSafetyTests(Base):
    def test_stalled_play_is_reported(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        path = self.play(max_quiet_runs=2)
        self.run_play(path, date(2026, 10, 20))
        self.run_play(path, date(2026, 10, 21))
        res = self.run_play(path, date(2026, 10, 22))
        self.assertTrue(res["stalled"])
        self.assertIn("found nobody new", self.report())

    def test_bad_play_and_missing_book_are_errors(self):
        with self.assertRaisesRegex(ValueError, "play type"):
            bp.build(self.ws, self.play(type="spray"), TODAY)
        with self.assertRaisesRegex(ValueError, "account-book"):
            bp.build(self.ws, self.play(), TODAY)

    def test_inputs_unchanged_and_only_play_folder_written(self):
        self.book([person("a", "A1")], [account("A1")])
        self.signals([sig("A1")])
        path = self.play()
        before = {p: p.read_bytes() for p in self.ws.rglob("*") if p.is_file()}
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bp.main(["--workspace", str(self.ws), "--play", str(path), "--today", "2026-10-20"])
        self.assertEqual(code, 0)
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data, p)
        new = {p for p in self.ws.rglob("*") if p.is_file()} - set(before)
        self.assertEqual({p.name for p in new}, {"enroll.csv", "funnel.md", "report.md", "state.json"})
        self.assertIn("Nothing was sent or enrolled", out.getvalue())

    def test_reads_excel_bom_csv(self):
        write(self.ws / "book/people.csv", PEOPLE, [person("a", "A1")], encoding="utf-8-sig")
        write(self.ws / "book/accounts.csv", ACCTS, [account("A1")], encoding="utf-8-sig")
        self.signals([sig("A1")])
        self.assertEqual(self.run_play(self.play())["proposed"], 1)


class ExampleTests(unittest.TestCase):
    def test_example_reproduces_committed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "example"
            shutil.copytree(EXAMPLE, ws)
            for pid in ("signal-oct", "winback-q4"):
                for name in ("enroll.csv", "funnel.md", "report.md", "state.json"):
                    (ws / "plays" / pid / name).unlink()
                bp.build(ws, ws / "plays" / pid / "play.json", TODAY)
                for name in ("enroll.csv", "funnel.md", "report.md"):
                    self.assertEqual((ws / "plays" / pid / name).read_text(),
                                     (EXAMPLE / "plays" / pid / name).read_text(), f"{pid}/{name}")
            sig_rows = {r["person_id"]: r for r in read(ws / "plays/signal-oct/enroll.csv")}
            self.assertEqual(sig_rows["p04"]["rank"], "1")
            self.assertEqual(sig_rows["p13"]["drop_reason"], "owned by jordan")


if __name__ == "__main__":
    unittest.main()
