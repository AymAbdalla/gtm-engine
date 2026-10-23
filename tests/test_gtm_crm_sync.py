"""Rules for aym-gtm crm-sync: matching, newer-wins, blanks, floors, bounces, carry-forward, rungs."""
import csv
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/crm-sync"
spec = importlib.util.spec_from_file_location("sync_crm", SKILL / "scripts/sync_crm.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

TODAY = date(2026, 10, 20)
PEOPLE = ["person_id", "account_id", "first_name", "last_name", "title", "email", "phone", "country", "status",
          "sequence", "tags", "crm_id", "updated_at"]
CRM = ["crm_id", "first_name", "last_name", "title", "email", "email_status", "phone", "country", "status",
       "account_name", "account_domain", "updated_at"]
LOG = ["activity_id", "timestamp", "person_id", "account_id", "channel", "direction", "sequence", "step",
       "play_id", "angle", "opener", "outcome", "notes", "source"]
ACCTS = ["account_id", "name", "domain", "other_domains", "crm_id"]


def write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def person(pid, crm="", **kw):
    r = {"person_id": pid, "account_id": "A1", "first_name": pid.title(), "last_name": "Test",
         "title": "Controller", "email": f"{pid}@acme.example", "country": "US", "status": "active", "crm_id": crm}
    r.update(kw)
    return r


def crm_row(crm, pid, **kw):
    r = {"crm_id": crm, "first_name": pid.title(), "last_name": "Test", "title": "Controller",
         "email": f"{pid}@acme.example", "email_status": "verified", "country": "US", "status": "active",
         "account_name": "Acme", "account_domain": "acme.example"}
    r.update(kw)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "gtm"
        self.ws.mkdir()
        (self.ws / "gtm.json").write_text(json.dumps({"sync": {"pilot_rows": 2}}))
        write(self.ws / "book/accounts.csv", ACCTS, [{"account_id": "A1", "name": "Acme", "domain": "acme.example", "crm_id": "CA1"}])

    def tearDown(self):
        self.tmp.cleanup()

    def setup(self, book, crm, log=(), state=None, activity=None, bounces=None):
        write(self.ws / "book/people.csv", PEOPLE, book)
        write(self.ws / "input/crm-export/people.csv", CRM, crm)
        write(self.ws / "log/activity.csv", LOG, list(log))
        if activity is not None:
            write(self.ws / "input/crm-export/activity.csv",
                  ["activity_id", "external_id", "timestamp", "crm_id", "channel", "direction", "outcome"], activity)
        if bounces is not None:
            write(self.ws / "input/crm-export/bounces.csv", ["crm_id", "email", "timestamp"], bounces)
        if state is not None:
            (self.ws / "sync").mkdir(exist_ok=True)
            (self.ws / "sync/state.json").write_text(json.dumps(state))

    def run_sync(self, **kw):
        return sync.run(self.ws, TODAY, **kw)

    def out(self, name):
        return read(self.ws / "sync" / name)


class FieldTests(Base):
    def test_one_side_changed_goes_to_the_other(self):
        self.setup([person("a", "C1", title="CFO"), person("b", "C2", phone="+1-312-555-0102")],
                   [crm_row("C1", "a", title="Controller"), crm_row("C2", "b", phone="+1-312-555-0199")],
                   state={"baseline": {"C1": {"title": "Controller"}, "C2": {"phone": "+1-312-555-0102"}}})
        self.run_sync()
        to_crm = {(r["record_id"], r["field"]): r for r in self.out("to-crm.csv")}
        self.assertEqual(to_crm[("C1", "title")]["new_value"], "CFO")
        self.assertEqual(to_crm[("C1", "title")]["current_value"], "Controller")
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["b"]["phone"], "+1-312-555-0199")
        self.assertNotIn(("C2", "phone"), to_crm)

    def test_both_changed_newer_time_wins_and_future_time_is_a_conflict(self):
        self.setup([person("a", "C1", title="Head of IT", updated_at="2026-10-18T10:00:00-04:00"),
                    person("b", "C2", title="CFO", updated_at="2026-10-18T10:00:00-04:00")],
                   [crm_row("C1", "a", title="IT Director", updated_at="2026-10-15T09:00:00-05:00"),
                    crm_row("C2", "b", title="VP Finance", updated_at="2026-11-30T09:00:00-05:00")],
                   state={"baseline": {"C1": {"title": "Director of IT"}, "C2": {"title": "Controller"}}})
        self.run_sync()
        to_crm = {(r["record_id"], r["field"]): r for r in self.out("to-crm.csv")}
        self.assertEqual(to_crm[("C1", "title")]["new_value"], "Head of IT")
        self.assertIn("newer", to_crm[("C1", "title")]["reason"])
        conflicts = self.out("conflicts.csv")
        self.assertEqual([(c["record_id"], c["field"]) for c in conflicts], [("C2", "title")])
        self.assertEqual(conflicts[0]["crm_time"], "")
        self.assertTrue(any("after today" in r["detail"] for r in self.out("review.csv")))

    def test_first_sync_without_times_is_a_conflict_not_a_guess(self):
        self.setup([person("a", "C1", title="CFO")], [crm_row("C1", "a", title="Controller")])
        self.run_sync()
        self.assertEqual(len(self.out("conflicts.csv")), 1)
        self.assertEqual([r for r in self.out("to-crm.csv") if r["field"] == "title"], [])

    def test_blank_never_clears_a_value(self):
        self.setup([person("a", "C1", phone="+1-312-555-0101"), person("b", "C2", phone="")],
                   [crm_row("C1", "a", phone=""), crm_row("C2", "b", phone="+1-312-555-0122")],
                   state={"baseline": {"C1": {"phone": "+1-312-555-0101"}}})
        self.run_sync()
        to_crm = {(r["record_id"], r["field"]): r for r in self.out("to-crm.csv")}
        self.assertEqual(to_crm[("C1", "phone")]["new_value"], "+1-312-555-0101")
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertNotIn("a", book)                       # the book phone is never cleared
        self.assertEqual(book["b"]["phone"], "+1-312-555-0122")

    def test_do_not_contact_wins_on_either_side(self):
        self.setup([person("a", "C1", status="do_not_contact"), person("b", "C2")],
                   [crm_row("C1", "a", status="active", updated_at="2026-10-19T09:00:00-04:00"),
                    crm_row("C2", "b", status="do_not_contact")],
                   state={"baseline": {"C1": {"status": "active"}, "C2": {"status": "active"}}})
        self.run_sync()
        to_crm = {(r["record_id"], r["field"]): r for r in self.out("to-crm.csv")}
        self.assertEqual(to_crm[("C1", "status")]["new_value"], "do_not_contact")
        self.assertEqual({r["person_id"]: r for r in self.out("to-book.csv")}["b"]["status"], "do_not_contact")


class MatchTests(Base):
    def test_every_export_row_is_accounted_for(self):
        self.setup([person("a", "C1"), person("x1", first_name="Alex", last_name="Rivera"),
                    person("x2", first_name="Alex", last_name="Rivera", email="ar2@acme.example")],
                   [crm_row("C1", "a"), crm_row("C9", "z", first_name="Alex", last_name="Rivera", email="other@acme.example"),
                    crm_row("C10", "new"), crm_row("C11", "far", account_name="Elsewhere", account_domain="elsewhere.example")])
        s = self.run_sync()
        self.assertEqual(s["matched"] + s["new_in_crm"] + s["review_people"], 4)
        self.assertEqual((s["matched"], s["new_in_crm"], s["review_people"]), (1, 1, 2))
        review = self.out("review.csv")
        self.assertTrue(any(r["issue"] == "ambiguous match" for r in review))
        self.assertTrue(any(r["issue"] == "not created in the CRM" and r["record_id"] == "x1" for r in review))
        creates = [r for r in self.out("to-crm.csv") if r["action"] == "create"]
        self.assertEqual(creates, [])                       # neither Alex is created while the match is open
        new = [r for r in self.out("to-book.csv") if r["crm_id"] == "C10"]
        self.assertEqual(new[0]["person_id"], "")
        self.assertEqual(new[0]["account_id"], "A1")

    def test_missing_from_new_export_is_closed_or_removed_never_deleted(self):
        self.setup([person("a", "C1"), person("b", "C2")], [crm_row("C1", "a")],
                   state={"export_ids": ["C1", "C2"]})
        self.run_sync()
        gone = [r for r in self.out("review.csv") if r["record_id"] == "C2"]
        self.assertEqual(gone[0]["issue"], "closed or removed in the CRM")
        self.assertNotIn("deleted", gone[0]["issue"])

    def test_create_row_carries_other_changes(self):
        self.setup([person("a", "C1"), person("s", "")], [crm_row("C1", "a")],
                   log=[{"activity_id": "x1", "timestamp": "2026-10-18T14:00:00-07:00", "person_id": "s",
                         "account_id": "A1", "channel": "email", "direction": "in", "outcome": "opt_out"}])
        self.run_sync()
        rows = [r for r in self.out("to-crm.csv") if r["record_id"] == "s"]
        self.assertEqual([r["action"] for r in rows], ["create"])
        self.assertIn("status=do_not_contact", rows[0]["new_value"])


class FloorTests(Base):
    def test_short_export_stops_and_keeps_state(self):
        state = {"datasets": {"people": {"hash": "x", "rows": 10}}, "watermark": "2026-10-15T00:00:00+00:00"}
        self.setup([person("a", "C1")], [crm_row("C1", "a")], state=state)
        before = (self.ws / "sync/state.json").read_text()
        s = self.run_sync()
        self.assertTrue(s["stopped"])
        self.assertEqual((self.ws / "sync/state.json").read_text(), before)
        self.assertFalse((self.ws / "sync/to-crm.csv").exists())
        self.assertIn("mass deletion", (self.ws / "sync/report.md").read_text())
        self.assertEqual(sync.main(["--workspace", str(self.ws), "--today", "2026-10-20"]), 1)


class ActivityTests(Base):
    def test_unknown_values_go_to_review_and_future_times_are_ignored(self):
        self.setup([person("a", "C1")], [crm_row("C1", "a")], log=[
            {"activity_id": "x1", "timestamp": "2026-10-19T11:00:00-04:00", "person_id": "a", "channel": "linkedin",
             "direction": "out", "outcome": "accepted"},
            {"activity_id": "x2", "timestamp": "2026-12-01T09:00:00-05:00", "person_id": "a", "channel": "email",
             "direction": "out", "outcome": "sent"}],
            activity=[{"activity_id": "CA-1", "timestamp": "2026-10-17T13:00:00-05:00", "crm_id": "C1",
                       "channel": "call", "direction": "out", "outcome": "left_voicemail"}])
        self.run_sync()
        issues = {r["record_id"]: r["issue"] for r in self.out("review.csv")}
        self.assertEqual(issues["x1"], "value not on the list")
        self.assertEqual(issues["x2"], "bad time in log/activity.csv")
        self.assertEqual(issues["CA-1"], "value not on the list")
        self.assertEqual(self.out("to-log.csv"), [])
        self.assertFalse(any(r["record_id"] in ("x1", "x2") for r in self.out("to-crm.csv")))

    def test_crm_activity_stays_in_to_log_until_appended_and_is_not_sent_back(self):
        self.setup([person("a", "C1")], [crm_row("C1", "a")],
                   activity=[{"activity_id": "CA-10", "timestamp": "2026-10-17T13:00:00-05:00", "crm_id": "C1",
                              "channel": "call", "direction": "out", "outcome": "no_answer"}])
        self.run_sync()
        self.run_sync()
        rows = self.out("to-log.csv")
        self.assertEqual([r["activity_id"] for r in rows], ["crm-CA-10"])
        with (self.ws / "log/activity.csv").open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=LOG, lineterminator="\n").writerow(rows[0])
        self.run_sync()
        self.assertEqual(self.out("to-log.csv"), [])
        self.assertFalse(any(r["record_id"] == "crm-CA-10" for r in self.out("to-crm.csv")))

    def test_outcome_change_carries_forward_until_the_book_shows_it(self):
        log = [{"activity_id": "x1", "timestamp": "2026-10-18T10:00:00-04:00", "person_id": "a", "account_id": "A1",
                "channel": "call", "direction": "out", "outcome": "booked"}]
        self.setup([person("a", "C1")], [crm_row("C1", "a")], log=log)
        self.run_sync()
        # a new export arrives, but nothing was applied yet: planned again
        write(self.ws / "input/crm-export/people.csv", CRM, [crm_row("C1", "a", updated_at="2026-10-19T09:00:00-04:00")])
        self.run_sync()
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["status"], "booked")
        self.assertIn("carried forward", self.out("to-book-reasons.csv")[0]["reason"])
        write(self.ws / "book/people.csv", PEOPLE, [person("a", "C1", status="booked")])
        self.run_sync()
        self.assertEqual([r for r in self.out("to-book.csv") if r["person_id"] == "a"], [])

    def test_reply_at_the_account_stops_other_sequences(self):
        log = [{"activity_id": "x1", "timestamp": "2026-10-14T10:00:00-04:00", "person_id": "a", "account_id": "A1",
                "channel": "email", "direction": "out", "sequence": "s1", "step": "1", "outcome": "sent"},
               {"activity_id": "x2", "timestamp": "2026-10-16T10:00:00-04:00", "person_id": "b", "account_id": "A1",
                "channel": "email", "direction": "in", "sequence": "s1", "step": "1", "outcome": "replied"},
               {"activity_id": "x3", "timestamp": "2026-10-16T10:00:00-04:00", "person_id": "c", "account_id": "A2",
                "channel": "email", "direction": "out", "sequence": "s1", "step": "1", "outcome": "sent"}]
        self.setup([person("a", "C1"), person("b", "C2"), person("c", "C3", account_id="A2")],
                   [crm_row("C1", "a"), crm_row("C2", "b"), crm_row("C3", "c")], log=log)
        self.run_sync()
        cad = {r["person_id"]: r for r in self.out("cadence.csv")}
        self.assertEqual(cad["b"]["state"], "replied")
        self.assertEqual(cad["a"]["state"], "stopped")
        self.assertIn("reply at the account", cad["a"]["reason"])
        self.assertEqual((cad["c"]["state"], cad["c"]["next_due"]), ("active", "2026-10-21"))


class BounceTests(Base):
    def test_bounce_tags_the_book_plans_the_crm_and_waits_for_confirmation(self):
        self.setup([person("a", "C1")], [crm_row("C1", "a")],
                   bounces=[{"crm_id": "C1", "email": "a@acme.example", "timestamp": "2026-10-18T08:00:00-04:00"}])
        self.run_sync()
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["tags"], "bounced")
        row = [r for r in self.out("to-crm.csv") if r["field"] == "email_status"][0]
        self.assertEqual((row["current_value"], row["new_value"]), ("verified", "invalid"))
        # a new people export arrives that still shows the address as fine: planned again
        write(self.ws / "input/crm-export/people.csv", CRM, [crm_row("C1", "a", updated_at="2026-10-19T09:00:00-04:00")])
        self.run_sync()
        self.assertTrue(any("not yet confirmed" in r["reason"] for r in self.out("to-crm.csv")))
        write(self.ws / "input/crm-export/people.csv", CRM, [crm_row("C1", "a", email_status="invalid")])
        s = self.run_sync()
        self.assertEqual(s["pending_bounces"], 0)
        self.assertIn("confirmed", (self.ws / "sync/report.md").read_text())
        # The book still lacks the tag (to-book.csv was not applied): clearing the pending bounce
        # never drops it.
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["tags"], "bounced")

    def test_crm_bounce_tags_the_book_once(self):
        log = [{"activity_id": "L1", "timestamp": "2026-10-18T08:00:00-04:00", "person_id": "b",
                "account_id": "A1", "channel": "email", "direction": "out", "outcome": "bounced", "source": "manual"}]
        self.setup([person("a", "C1"), person("b", "C2"), person("c", "C3", tags="bounced")],
                   [crm_row("C1", "a", email_status="Invalid"), crm_row("C2", "b", email_status="invalid"),
                    crm_row("C3", "c", email_status="invalid")], log=log)
        self.run_sync()
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["tags"], "bounced")     # no pending bounce: the CRM alone is enough
        self.assertEqual(book["b"]["tags"], "bounced")     # a logged bounce too: planned once
        self.assertNotIn("c", book)                        # the book already has it
        reasons = [r for r in self.out("to-book-reasons.csv") if r["field"] == "tags"]
        self.assertEqual(sorted(r["person_id"] for r in reasons), ["a", "b"])
        self.assertIn("the CRM marks the address as bounced",
                      next(r["reason"] for r in reasons if r["person_id"] == "a"))


class RungTests(Base):
    def test_live_rung_and_writing_into_inputs_are_refused(self):
        self.setup([person("a", "C1")], [crm_row("C1", "a")])
        with self.assertRaisesRegex(ValueError, "only plans"):
            self.run_sync(rung="live")
        with self.assertRaisesRegex(ValueError, "input"):
            self.run_sync(out=self.ws / "input/sync")

    def test_copy_rung_checks_current_value_and_logs_each_row(self):
        self.setup([person("a", "C1", title="CFO"), person("b", "C2", title="VP")],
                   [crm_row("C1", "a", title="Controller"), crm_row("C2", "b", title="Controller")],
                   state={"baseline": {"C1": {"title": "Controller"}, "C2": {"title": "Controller"}}})
        self.run_sync(rung="copy")
        log = {r["row_id"]: r["status"] for r in read(self.ws / "sync/copy/row-log.csv")}
        self.assertEqual(sorted(log.values()), ["applied", "applied"])
        copy_rows = {r["crm_id"]: r for r in read(self.ws / "sync/copy/people.csv")}
        self.assertEqual(copy_rows["C1"]["title"], "CFO")
        pilot = [r for r in self.out("to-crm.csv") if r["pilot"] == "yes"]
        self.assertEqual(len(pilot), 2)


class RoundThreeTests(Base):
    def test_crm_opt_out_becomes_do_not_contact_in_the_same_run_and_is_never_lost(self):
        self.setup([person("a", "C1"), person("b", "C2")], [crm_row("C1", "a"), crm_row("C2", "b")],
                   activity=[{"activity_id": "CA-5", "timestamp": "2026-10-17T13:00:00-05:00", "crm_id": "C1",
                              "channel": "email", "direction": "in", "outcome": "opt_out"},
                             {"activity_id": "CA-6", "timestamp": "2026-10-19T09:00:00-05:00", "crm_id": "C2",
                              "channel": "call", "direction": "out", "outcome": "no_answer"}])
        self.run_sync()
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["status"], "do_not_contact")
        self.assertIn("opted_out", book["a"]["tags"])
        crm = [r for r in self.out("to-crm.csv") if r["record_id"] == "C1" and r["field"] == "status"]
        self.assertEqual(crm[0]["new_value"], "do_not_contact")
        # the user appends to-log.csv; the next sync must neither lose nor double the opt-out
        rows = self.out("to-log.csv")
        with (self.ws / "log/activity.csv").open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG, lineterminator="\n")
            for r in rows:
                w.writerow(r)
        self.run_sync()
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["status"], "do_not_contact")
        reasons = [r for r in self.out("to-book-reasons.csv") if r["person_id"] == "a" and r["field"] == "status"]
        self.assertEqual(len(reasons), 1)
        self.assertIn("carried forward", reasons[0]["reason"])
        # once the book and the CRM show it, it leaves the plan
        write(self.ws / "book/people.csv", PEOPLE, [person("a", "C1", status="do_not_contact", tags="opted_out"),
                                                     person("b", "C2")])
        write(self.ws / "input/crm-export/people.csv", CRM, [crm_row("C1", "a", status="Do Not Contact"),
                                                              crm_row("C2", "b")])
        self.run_sync()
        self.assertFalse(any(r["person_id"] == "a" for r in self.out("to-book.csv")))
        self.assertFalse(any(r["record_id"] == "C1" and r["field"] == "status" for r in self.out("to-crm.csv")))

    def test_status_map_and_unknown_crm_status(self):
        self.setup([person("a", "C1"), person("b", "C2"), person("c", "C3", status="nurture")],
                   [crm_row("C1", "a", status="Do Not Contact"), crm_row("C2", "b", status="Nurture - Q1"),
                    crm_row("C3", "c", status="NURTURE")],
                   state={"baseline": {"C1": {"status": "active"}, "C2": {"status": "active"}}})
        self.run_sync()
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["status"], "do_not_contact")        # mapped, and do-not-contact wins
        self.assertNotIn("b", book)                                    # unknown value never reaches the book
        self.assertNotIn("c", book)                                    # "NURTURE" maps to nurture: no change
        review = [r for r in self.out("review.csv") if r["issue"] == "unknown CRM status"]
        self.assertEqual([r["record_id"] for r in review], ["C2"])
        self.assertIn("status_map", (self.ws / "sync/report.md").read_text())

    def test_same_inputs_give_the_same_plan_and_keep_the_state(self):
        self.setup([person("a", "C1"), person("b", "C2")], [crm_row("C1", "a")],
                   state={"export_ids": ["C1", "C2"]},
                   bounces=[{"crm_id": "C1", "email": "a@acme.example", "timestamp": "2026-10-18T08:00:00-04:00"}])
        self.run_sync()
        first = {n: (self.ws / "sync" / n).read_text() for n in ("to-crm.csv", "to-book.csv", "review.csv")}
        state = (self.ws / "sync/state.json").read_text()
        s = self.run_sync()
        self.assertTrue(s["rerun"])
        self.assertEqual({n: (self.ws / "sync" / n).read_text() for n in first}, first)
        self.assertEqual((self.ws / "sync/state.json").read_text(), state)
        gone = [r for r in self.out("review.csv") if r["record_id"] == "C2"]
        self.assertEqual(gone[0]["issue"], "closed or removed in the CRM")    # still, on the rerun

    def test_repeated_create_and_log_rows_ask_for_a_search_first(self):
        log = [{"activity_id": "a1", "timestamp": "2026-10-19T10:00:00-04:00", "person_id": "a", "account_id": "A1",
                "channel": "call", "direction": "out", "outcome": "connected", "source": "manual"}]
        self.setup([person("a", "C1"), person("n")], [crm_row("C1", "a")], log=log)
        self.run_sync()
        first = {r["action"]: r for r in self.out("to-crm.csv") if r["action"] in ("create", "log")}
        self.assertEqual(set(first), {"create", "log"})
        self.assertFalse(any("planned first on" in r["reason"] for r in first.values()))
        # next day, a new export that still does not show them
        write(self.ws / "input/crm-export/people.csv", CRM, [crm_row("C1", "a", title="CFO")])
        sync.run(self.ws, TODAY + timedelta(days=1))
        again = {r["action"]: r for r in self.out("to-crm.csv") if r["action"] in ("create", "log")}
        for r in again.values():
            self.assertIn("planned first on 2026-10-20", r["reason"])
            self.assertIn("search the CRM", r["reason"])
        self.assertIn("Search the CRM for each before applying it again", (self.ws / "sync/report.md").read_text())

    def test_state_is_written_whole_or_not_at_all(self):
        self.setup([person("a", "C1")], [crm_row("C1", "a")])
        self.run_sync()
        self.assertTrue((self.ws / "sync/state.json").exists())
        self.assertFalse((self.ws / "sync/state.json.tmp").exists())
        target = self.ws / "sync/other.json"
        target.write_text("old")
        real = sync.os.replace
        try:
            def boom(src, dst):
                raise OSError("disk full")
            sync.os.replace = boom
            with self.assertRaises(OSError):
                sync.write_atomic(target, "new")
        finally:
            sync.os.replace = real
        self.assertEqual(target.read_text(), "old")      # an interrupted write leaves the old file

    def test_copy_rung_never_saves_state(self):
        self.setup([person("a", "C1", title="CFO")], [crm_row("C1", "a", title="Controller")],
                   state={"baseline": {"C1": {"title": "Controller"}}, "export_ids": ["C1"]})
        before = (self.ws / "sync/state.json").read_text()
        s = self.run_sync(rung="copy")
        self.assertFalse(s["state_saved"])
        self.assertEqual((self.ws / "sync/state.json").read_text(), before)
        self.assertIn("state was not saved", (self.ws / "sync/report.md").read_text())

    def test_a_stopped_run_marks_the_old_plan_stale(self):
        self.setup([person("a", "C1", title="CFO")], [crm_row("C1", "a", title="Controller")],
                   state={"baseline": {"C1": {"title": "Controller"}}})
        self.run_sync()
        self.assertTrue((self.ws / "sync/to-crm.csv").exists())
        state = json.loads((self.ws / "sync/state.json").read_text())
        state["datasets"]["people"]["rows"] = 50                       # the next export looks far too short
        (self.ws / "sync/state.json").write_text(json.dumps(state))
        write(self.ws / "input/crm-export/people.csv", CRM, [crm_row("C1", "a", title="Head of Finance")])
        s = self.run_sync()
        self.assertTrue(s["stopped"])
        self.assertFalse((self.ws / "sync/to-crm.csv").exists())
        self.assertTrue((self.ws / "sync/to-crm.stale.csv").exists())
        self.assertIn("to-crm.stale.csv", (self.ws / "sync/report.md").read_text())

    def test_person_and_account_disagree_goes_to_review(self):
        self.setup([person("a", "C1")], [crm_row("C1", "a")], log=[
            {"activity_id": "x1", "timestamp": "2026-10-19T11:00:00-04:00", "person_id": "a", "account_id": "A9",
             "channel": "email", "direction": "out", "outcome": "sent"}],
            activity=[])
        write(self.ws / "input/crm-export/activity.csv",
              ["activity_id", "timestamp", "crm_id", "channel", "direction", "outcome", "account_name", "account_domain"],
              [{"activity_id": "CA-7", "timestamp": "2026-10-19T10:00:00-04:00", "crm_id": "C1", "channel": "call",
                "direction": "out", "outcome": "no_answer", "account_name": "Elsewhere", "account_domain": "elsewhere.example"}])
        self.run_sync()
        issues = {r["record_id"]: r["issue"] for r in self.out("review.csv")}
        self.assertEqual(issues["x1"], "person and account disagree")
        self.assertEqual(issues["CA-7"], "person and account disagree")
        self.assertFalse(any(r["record_id"] == "x1" for r in self.out("to-crm.csv")))
        self.assertEqual(self.out("to-log.csv"), [])

    def test_stop_outcome_with_wrong_account_still_stops_the_person(self):
        self.setup([person("a", "C1"), person("b", "C2")], [crm_row("C1", "a"), crm_row("C2", "b")], log=[
            {"activity_id": "x2", "timestamp": "2026-10-19T11:00:00-04:00", "person_id": "a", "account_id": "A9",
             "channel": "email", "direction": "in", "outcome": "opt_out"}],
            activity=[])
        write(self.ws / "input/crm-export/activity.csv",
              ["activity_id", "timestamp", "crm_id", "channel", "direction", "outcome", "account_name", "account_domain"],
              [{"activity_id": "CA-8", "timestamp": "2026-10-19T10:00:00-04:00", "crm_id": "C2", "channel": "call",
                "direction": "out", "outcome": "wrong_person", "account_name": "Elsewhere",
                "account_domain": "elsewhere.example"}])
        self.run_sync()
        issues = {r["record_id"]: r["issue"] for r in self.out("review.csv")}
        self.assertEqual(issues["x2"], "person and account disagree")
        self.assertEqual(issues["CA-8"], "person and account disagree")
        book = {r["person_id"]: r for r in self.out("to-book.csv")}
        self.assertEqual(book["a"]["status"], "do_not_contact")
        self.assertEqual(book["b"]["status"], "wrong_person")
        crm = [(r["record_id"], r["field"], r["new_value"]) for r in self.out("to-crm.csv")]
        self.assertIn(("C1", "status", "do_not_contact"), crm)
        self.assertFalse(any(r[0] in ("x2", "CA-8") for r in crm))   # the activity rows stay in review
        self.assertEqual(self.out("to-log.csv"), [])


OPP = ["opportunity_id", "account_crm_id", "stage", "is_closed", "owner", "updated_at"]
ACCT_UPD = ["account_id", "crm_id", "status", "owner", "relationship", "reason"]


class AccountStatusTests(Base):
    """Open deals, owners and relationships come from the CRM into the book (to-book-accounts.csv)."""

    def setUp(self):
        super().setUp()
        write(self.ws / "book/accounts.csv", ACCTS + ["status", "owner", "relationship"], [
            {"account_id": "A1", "name": "Acme", "domain": "acme.example", "crm_id": "CA1", "status": "active"},
            {"account_id": "A2", "name": "Beta", "domain": "beta.example", "crm_id": "CA2", "status": "live_deal"}])
        self.setup([person("p1", "C1")], [crm_row("C1", "p1")])

    def test_open_opportunity_sets_live_deal_and_a_closed_one_clears_it(self):
        write(self.ws / "input/crm-export/opportunities.csv", OPP, [
            {"opportunity_id": "O1", "account_crm_id": "CA1", "stage": "Demo", "is_closed": "false", "owner": "ae-1"},
            {"opportunity_id": "O2", "account_crm_id": "CA2", "stage": "Closed Lost", "is_closed": "true", "owner": "ae-2"}])
        self.run_sync()
        rows = {r["account_id"]: r for r in read(self.ws / "sync/to-book-accounts.csv")}
        self.assertEqual(rows["A1"]["status"], "live_deal")
        self.assertIn("O1", rows["A1"]["reason"])
        self.assertEqual(rows["A2"]["status"], "active")
        self.assertIn("no open opportunity", rows["A2"]["reason"])
        self.assertIn("account-updates.csv", (self.ws / "sync/report.md").read_text())

    def test_crm_account_owner_and_relationship_come_into_the_book(self):
        write(self.ws / "input/crm-export/accounts.csv", ["crm_id", "name", "domain", "owner", "relationship"], [
            {"crm_id": "CA1", "name": "Acme", "domain": "acme.example", "owner": "jordan", "relationship": "customer"},
            {"crm_id": "CA2", "name": "Beta", "domain": "beta.example", "owner": "", "relationship": ""}])
        self.run_sync()
        rows = {r["account_id"]: r for r in read(self.ws / "sync/to-book-accounts.csv")}
        self.assertEqual((rows["A1"]["owner"], rows["A1"]["relationship"]), ("jordan", "customer"))
        self.assertNotIn("A2", rows)   # a blank in the CRM never clears the book

    def test_without_an_opportunities_export_live_deal_is_left_alone(self):
        self.run_sync()
        self.assertEqual(read(self.ws / "sync/to-book-accounts.csv"), [])

    def test_a_live_deal_missing_from_the_export_stays_live(self):
        # Oct 22 check finding: a partial opportunities export put live deals back to active.
        write(self.ws / "input/crm-export/opportunities.csv", OPP, [
            {"opportunity_id": "O1", "account_crm_id": "CA1", "stage": "Demo", "is_closed": "false", "owner": "ae-1"}])
        self.run_sync()
        rows = {r["account_id"]: r for r in read(self.ws / "sync/to-book-accounts.csv")}
        self.assertNotIn("A2", rows)
        self.assertIn("Live deal kept at A2", (self.ws / "sync/report.md").read_text())

    def test_a_much_shorter_opportunities_export_stops_the_run(self):
        opps = [{"opportunity_id": f"O{i}", "account_crm_id": "CA9", "stage": "Closed Lost",
                 "is_closed": "true", "owner": "ae-1"} for i in range(10)]
        write(self.ws / "input/crm-export/opportunities.csv", OPP, opps)
        self.run_sync()
        write(self.ws / "input/crm-export/opportunities.csv", OPP, opps[:3])
        self.run_sync()
        self.assertIn("opportunities.csv has 3 rows", (self.ws / "sync/report.md").read_text())


class MappingConfirmationTests(Base):
    """D1 (Oct 22): with no confirmed mapping the plan still runs, and says so at the top."""

    def test_unconfirmed_mapping_is_flagged_and_confirmed_is_not(self):
        self.setup([person("p1", "C1")], [crm_row("C1", "p1")])
        self.run_sync()
        report = (self.ws / "sync/report.md").read_text()
        self.assertIn("Mapping unconfirmed", report.splitlines()[2])
        self.run_sync(mapping_confirmed=True)
        self.assertNotIn("Mapping unconfirmed", (self.ws / "sync/report.md").read_text())


class ExampleTests(unittest.TestCase):
    def test_example_matches_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "gtm"
            shutil.copytree(SKILL / "assets/example", ws)
            sync.run(ws, TODAY)
            for f in sorted((SKILL / "assets/example/expected").iterdir()):
                self.assertEqual((ws / "sync" / f.name).read_text(), f.read_text(), f.name)


if __name__ == "__main__":
    unittest.main()
