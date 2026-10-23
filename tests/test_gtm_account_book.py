"""Rules of the aym-gtm account-book scripts, checked on made-up data."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/account-book"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


book = load("build_book")
rank = load("rank_accounts")

PEOPLE = book.PEOPLE_COLS
ACCTS = book.ACCOUNT_COLS


def write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def person(**kw):
    base = {"status": "active", "email_status": "verified", "email_score": "95", "country": "US"}
    base.update(kw)
    if "email" not in kw and kw.get("first_name"):
        base["email"] = f"{kw['first_name'].lower()}@acme.example"
    return base


CFG = {
    "icp": {"size": {"min": 200}},
    "personas": [
        {"id": "cfo", "lane": "finance", "role": "decision_maker", "title_patterns": ["\\bcfo\\b", "vp finance"]},
        {"id": "controller", "lane": "finance", "role": "champion", "title_patterns": ["controller"]},
        {"id": "it", "lane": "tech", "role": "technical_gatekeeper", "title_patterns": ["head of it"]},
    ],
    "book": {"sources": ["input/researched.csv", "input/people.csv"], "ready_min": 2},
    "ranking": {"top_n": 2},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "gtm"
        (self.ws / "input").mkdir(parents=True)
        (self.ws / "gtm.json").write_text(json.dumps(CFG))
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "500", "country": "US", "tier": "P1", "status": "active"},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def people(self):
        return {r["person_id"]: r for r in read(self.ws / "book/people.csv")}

    def accounts(self):
        return {r["account_id"]: r for r in read(self.ws / "book/accounts.csv")}

    def build(self, today="2026-10-20", **kw):
        return book.build(self.ws, self.ws / "book", today, **kw)


class MergeTests(Base):
    def test_higher_source_wins_lower_fills_blanks(self):
        write(self.ws / "input/researched.csv", PEOPLE, [person(first_name="Ana", last_name="Lee", account_id="A1", title="VP Finance")])
        write(self.ws / "input/people.csv", PEOPLE, [person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1",
                                                           title="Finance Manager", phone="+1-312-555-0101", crm_id="C1")])
        self.build()
        p = self.people()["p1"]  # the CRM's real id is kept
        self.assertEqual(p["title"], "VP Finance")
        self.assertEqual(p["phone"], "+1-312-555-0101")
        self.assertEqual(p["source"], "researched;people")

    def test_exact_name_match_but_never_fuzzy(self):
        write(self.ws / "input/researched.csv", PEOPLE, [
            person(first_name="Ana", last_name="Lee", account_id="A1", email="", title="CFO"),
            person(first_name="Anna", last_name="Lee", account_id="A1", email="", title="Controller")])
        write(self.ws / "input/people.csv", PEOPLE, [person(person_id="p1", first_name="ana", last_name="LEE", account_id="A1")])
        res = self.build()
        self.assertEqual(res["people"], 2)  # "Anna" is not merged into "Ana"

    def test_ambiguous_name_goes_to_conflicts(self):
        write(self.ws / "input/researched.csv", PEOPLE, [])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Sam", last_name="Ito", account_id="A1", email="sam1@acme.example"),
            person(person_id="p2", first_name="Sam", last_name="Ito", account_id="A1", email="sam2@acme.example"),
            person(first_name="Sam", last_name="Ito", account_id="A1", email="")])
        res = self.build()
        self.assertEqual(res["people"], 3)
        self.assertEqual(res["conflicts"], 1)


class RebuildTests(Base):
    def first_build(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="CFO", phone="+1-312-555-0101"),
            person(person_id="p2", first_name="Bo", last_name="Kim", account_id="A1", title="Controller", phone="+1-312-555-0102"),
            person(person_id="p3", first_name="Cy", last_name="Day", account_id="A1", title="Head of IT")])
        self.build("2026-10-12")
        rows = read(self.ws / "book/people.csv")
        for r in rows:
            if r["person_id"] == "p1":
                r["title"] = "CFO and COO"
                r["new_note"] = "Asked for a call next month"
                r["status"] = "nurture"
            if r["person_id"] == "p2":
                r["timezone"] = "America/Denver"
        rows.append(dict({c: "" for c in rows[0]}, person_id="m1", account_id="A1", first_name="Di",
                         last_name="Ono", title="Controller", status="active", tags="met_in_person"))
        write(self.ws / "book/people.csv", list(rows[0].keys()), rows)

    def test_user_edits_survive_source_changes(self):
        self.first_build()
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="Chief Financial Officer",
                   phone="+1-312-555-0111", status="active"),
            person(person_id="p2", first_name="Bo", last_name="Kim", account_id="A1", title="Controller", phone=""),
            person(person_id="p3", first_name="Cy", last_name="Day", account_id="A1", title="Head of IT", tags="opted_out")])
        self.build("2026-10-20")
        p = self.people()
        self.assertEqual(p["p1"]["title"], "CFO and COO")             # edited field kept
        self.assertEqual(p["p1"]["phone"], "+1-312-555-0111")         # unedited field updates
        self.assertEqual(p["p1"]["status"], "nurture")                # status is yours
        self.assertEqual(p["p1"]["notes"], "2026-10-20: Asked for a call next month")
        self.assertEqual(p["p1"]["new_note"], "")
        self.assertEqual(p["p2"]["phone"], "+1-312-555-0102")         # blank source never deletes
        self.assertEqual(p["p2"]["timezone_source"], "manual")
        self.assertEqual(p["p3"]["status"], "do_not_contact")         # opt-out beats everything
        self.assertEqual(p["m1"]["source"], "manual")                 # hand-added person stays
        self.assertEqual(p["m1"]["tags"], "met_in_person")
        # a third build keeps the manual time zone label and does not repeat the note
        self.build("2026-10-21")
        p = self.people()
        self.assertEqual(p["p2"]["timezone_source"], "manual")
        self.assertEqual(p["p1"]["notes"], "2026-10-20: Asked for a call next month")

    def test_edits_survive_three_rebuilds(self):
        self.first_build()
        snapshot = [person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="CFO",
                           phone="+1-312-555-0101", email="ana@acme.example")]
        write(self.ws / "input/crm-snapshot.csv", PEOPLE, snapshot)
        for day in ("2026-10-20", "2026-10-21", "2026-10-22"):
            self.build(day)
            p = self.people()
            self.assertEqual(p["p1"]["title"], "CFO and COO", day)   # typed title kept every time
            self.assertEqual(p["p1"]["status"], "nurture", day)      # hand-set status kept
            fixes = {(f["person_id"], f["field"]) for f in read(self.ws / "book/fixes.csv")}
            self.assertIn(("p1", "title"), fixes, day)               # the CRM still needs your title
            conflicts = read(self.ws / "book/conflicts.csv")
            self.assertEqual([c for c in conflicts if c["field"] == "status"], [], day)
        built = {r["person_id"]: r for r in read(self.ws / "book/.built/people.csv")}
        self.assertEqual(built["p1"]["title"], "CFO")                # .built holds the source value
        self.assertNotIn("m1", built)                                # hand-added rows never enter .built

    def test_blank_source_then_new_value_updates_the_book(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p2", first_name="Bo", last_name="Kim", account_id="A1", title="Controller",
                   phone="+1-312-555-0102")])
        self.build("2026-10-12")
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p2", first_name="Bo", last_name="Kim", account_id="A1", title="Controller", phone="")])
        self.build("2026-10-13")
        self.assertEqual(self.people()["p2"]["phone"], "+1-312-555-0102")   # blank never deletes
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p2", first_name="Bo", last_name="Kim", account_id="A1", title="Controller",
                   phone="+1-312-555-0199")])
        self.build("2026-10-14")
        self.assertEqual(self.people()["p2"]["phone"], "+1-312-555-0199")   # the new source value wins
        self.assertNotIn("p2", {f["person_id"] for f in read(self.ws / "book/fixes.csv")})

    def test_blank_account_headcount_then_new_value_updates(self):
        write(self.ws / "input/people.csv", PEOPLE, [person(person_id="p1", first_name="A", last_name="B", account_id="A1", title="CFO")])
        acct = {"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "270", "country": "US"}
        write(self.ws / "input/accounts.csv", ACCTS, [acct])
        self.build("2026-10-12")
        write(self.ws / "input/accounts.csv", ACCTS, [dict(acct, employees="")])
        self.build("2026-10-13")
        self.assertEqual(self.accounts()["A1"]["employees"], "270")
        write(self.ws / "input/accounts.csv", ACCTS, [dict(acct, employees="150")])
        self.build("2026-10-14")
        a = self.accounts()["A1"]
        self.assertEqual(a["employees"], "150")
        self.assertEqual(a["strategy"], "hold")                              # now below the size floor

    def test_source_status_change_is_a_conflict(self):
        self.first_build()
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="CFO", status="left")])
        self.build("2026-10-20")
        conflicts = read(self.ws / "book/conflicts.csv")
        self.assertEqual([(c["person_id"], c["source_value"]) for c in conflicts if c["field"] == "status"],
                         [("p1", "left")])
        self.assertEqual(self.people()["p1"]["status"], "nurture")

    def test_area_code_time_zone_is_not_an_edit(self):
        cfg = dict(CFG, book=dict(CFG["book"], area_code_tz={"312": "America/Chicago", "617": "America/New_York"}))
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="CFO", phone="+1-312-555-0101")])
        self.build("2026-10-12")
        self.assertEqual(self.people()["p1"]["timezone_source"], "area_code_approx")
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="CFO", phone="+1-617-555-0101")])
        self.build("2026-10-20")
        p = self.people()["p1"]
        self.assertEqual((p["timezone"], p["timezone_source"]), ("America/New_York", "area_code_approx"))

    def test_tags_only_grow(self):
        self.first_build()
        rows = read(self.ws / "book/people.csv")
        for r in rows:
            if r["person_id"] == "p2":
                r["tags"] = "replied"
        write(self.ws / "book/people.csv", list(rows[0].keys()), rows)
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p2", first_name="Bo", last_name="Kim", account_id="A1", title="Controller", tags="bounced")])
        self.build("2026-10-20")
        self.assertEqual(self.people()["p2"]["tags"], "replied;bounced")


class SourceFileTests(Base):
    def test_missing_required_source_stops_and_writes_nothing(self):
        write(self.ws / "input/researched.csv", PEOPLE, [
            person(first_name="Dana", last_name="Okafor", account_id="A1", title="CFO")])
        with self.assertRaisesRegex(ValueError, "required source file missing: input/people.csv"):
            self.build()
        self.assertFalse((self.ws / "book").exists())

    def test_missing_optional_source_is_a_warning(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Dana", last_name="Okafor", account_id="A1", title="CFO")])
        res = self.build()
        self.assertEqual(res["people"], 1)
        self.assertIn("listed source input/researched.csv is missing and was skipped", res["warnings"])

    def test_real_ids_replace_made_up_ids_without_duplicates(self):
        # First build: only the researched list exists, so ids are made up.
        cfg = json.loads((self.ws / "gtm.json").read_text())
        cfg["book"]["required_sources"] = []
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        write(self.ws / "input/researched.csv", PEOPLE, [
            person(first_name="Dana", last_name="Okafor", account_id="A1", title="CFO", phone="+1-312-555-0151"),
            person(first_name="Ezra", last_name="Whitfield", account_id="A1", title="Controller", email="")])
        self.build()
        first = self.people()
        self.assertTrue(all(book.is_generated_id(pid) for pid in first))
        dana_tmp = next(pid for pid, r in first.items() if r["first_name"] == "Dana")
        # The user edits Dana's title in the book.
        rows = read(self.ws / "book/people.csv")
        for r in rows:
            if r["person_id"] == dana_tmp:
                r["title"] = "Chief Financial Officer"
        write(self.ws / "book/people.csv", list(rows[0].keys()), rows)
        # Then the real people list arrives with real ids.
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p01", crm_id="C-P01", first_name="Dana", last_name="Okafor", account_id="A1", title="CFO"),
            person(person_id="p12", crm_id="C-P12", first_name="Ezra", last_name="Whitfield", account_id="A1",
                   title="Controller", email="ezra.whitfield@acme.example")])
        res = self.build()
        p = self.people()
        self.assertEqual(sorted(p), ["p01", "p12"])            # no duplicate, real ids kept
        self.assertEqual(p["p01"]["crm_id"], "C-P01")
        self.assertEqual(p["p01"]["title"], "Chief Financial Officer")  # the edit survived
        self.assertEqual(p["p12"]["email"], "ezra.whitfield@acme.example")
        self.assertEqual(res["ids_adopted"], 2)
        notes = [c for c in read(self.ws / "book/conflicts.csv") if c["field"] == "person_id"]
        self.assertEqual({c["book_value"] for c in notes}, {dana_tmp, next(pid for pid in first if pid != dana_tmp)})
        res = self.build()                                       # a third build changes nothing
        self.assertEqual(sorted(self.people()), ["p01", "p12"])
        self.assertEqual(res["ids_adopted"], 0)

    def test_status_change_in_the_book_is_a_crm_fix(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", crm_id="C1", first_name="Nadia", last_name="Kowalski", account_id="A1",
                   title="CFO", tags="opted_out")])
        write(self.ws / "input/crm-snapshot.csv", PEOPLE, [
            person(person_id="p1", crm_id="C1", first_name="Nadia", last_name="Kowalski", account_id="A1",
                   title="CFO", status="active")])
        self.build()
        fixes = read(self.ws / "book/fixes.csv")
        self.assertIn({"person_id": "p1", "crm_id": "C1", "field": "status", "crm_value": "active",
                       "book_value": "do_not_contact"}, fixes)


class GateTests(Base):
    def test_send_gate_reasons(self):
        rows = [
            person(person_id="ok", first_name="Ok", last_name="A", account_id="A1", title="CFO"),
            person(person_id="ca", first_name="Ca", last_name="B", account_id="A1", email_status="catch_all", email_score="99"),
            person(person_id="lo", first_name="Lo", last_name="C", account_id="A1", email_score="50"),
            person(person_id="ns", first_name="Ns", last_name="D", account_id="A1", email_score=""),
            person(person_id="od", first_name="Od", last_name="E", account_id="A1", email="od@other.example"),
            person(person_id="sq", first_name="Sq", last_name="F", account_id="A1", sequence="seq-1"),
            person(person_id="hd", first_name="Hd", last_name="G", account_id="A1", status="hold"),
            person(person_id="uk", first_name="Uk", last_name="H", account_id="A1", country="GB"),
        ]
        write(self.ws / "input/people.csv", PEOPLE, rows)
        self.build()
        p = self.people()
        self.assertEqual(p["ok"]["send_ok"], "yes")
        self.assertIn("catch-all", p["ca"]["send_block_reason"])
        self.assertIn("below 80", p["lo"]["send_block_reason"])
        self.assertIn("no email score", p["ns"]["send_block_reason"])
        self.assertIn("not on the account's domains", p["od"]["send_block_reason"])
        self.assertIn("already in sequence", p["sq"]["send_block_reason"])
        self.assertIn("status hold", p["hd"]["send_block_reason"])
        self.assertIn("country GB", p["uk"]["send_block_reason"])
        for pid in ("ca", "lo", "ns", "od", "sq", "hd", "uk"):
            self.assertEqual(p[pid]["send_ok"], "no", pid)

    def test_export_lists_who_was_left_out(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="ok", first_name="Ok", last_name="A", account_id="A1", title="CFO"),
            person(person_id="dn", first_name="Dn", last_name="B", account_id="A1", status="do_not_contact")])
        res = self.build(export_ids=["A1"])
        self.assertEqual(res["exported"], 1)
        left = read(self.ws / "book/export-left-out.csv")
        self.assertEqual([r["person_id"] for r in left], ["dn"])
        self.assertIn("do_not_contact", left[0]["left_out_reason"])

    def test_linkedin_gate_blocks_the_same_people_and_needs_a_profile(self):
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "500", "tier": "P1"},
            {"account_id": "A2", "name": "Rival", "domain": "rival.example", "employees": "500", "relationship": "competitor"},
            {"account_id": "A3", "name": "Paused", "domain": "paused.example", "employees": "500", "status": "hold"},
            {"account_id": "A4", "name": "Deal", "domain": "deal.example", "employees": "500", "status": "live_deal"}])
        li = "https://linkedin.example/in/x"
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="ok", first_name="Ok", last_name="A", account_id="A1", title="CFO", email="", linkedin_url=li),
            person(person_id="np", first_name="Np", last_name="B", account_id="A1", title="CFO", linkedin_url=""),
            person(person_id="sr", first_name="Sr", last_name="C", account_id="A1", title="Sales Representative", linkedin_url=li),
            person(person_id="op", first_name="Op", last_name="D", account_id="A1", title="CFO", tags="opted_out", linkedin_url=li),
            person(person_id="cp", first_name="Cp", last_name="E", account_id="A2", title="CFO", email="cp@rival.example", linkedin_url=li),
            person(person_id="hd", first_name="Hd", last_name="F", account_id="A3", title="CFO", email="hd@paused.example", linkedin_url=li),
            person(person_id="ld", first_name="Ld", last_name="G", account_id="A4", title="CFO", email="ld@deal.example", linkedin_url=li)])
        self.build()
        p = self.people()
        self.assertEqual((p["ok"]["linkedin_ok"], p["ok"]["send_ok"]), ("yes", "no"))   # no email, LinkedIn still fine
        expect = {"np": "no LinkedIn URL", "sr": "title is not a buyer", "op": "tag opted_out",
                  "cp": "relationship is competitor", "hd": "on hold", "ld": "live deal"}
        for pid, why in expect.items():
            self.assertEqual(p[pid]["linkedin_ok"], "no", pid)
            self.assertIn(why, p[pid]["linkedin_block_reason"], pid)

    def test_gate_blocks_accounts_and_people_we_must_not_email(self):
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "500", "tier": "P1"},
            {"account_id": "A2", "name": "Rival", "domain": "rival.example", "employees": "500", "relationship": "competitor"},
            {"account_id": "A3", "name": "Sub", "domain": "sub.example", "employees": "500", "relationship": "parent_decides"},
            {"account_id": "A4", "name": "Deal", "domain": "deal.example", "employees": "500", "status": "live_deal"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="ok", first_name="Ok", last_name="A", account_id="A1", title="CFO"),
            person(person_id="sr", first_name="Sr", last_name="B", account_id="A1", title="Sales Representative"),
            person(person_id="nt", first_name="Nt", last_name="C", account_id="A1", title="CFO", notes="Said do not contact again"),
            person(person_id="dt", first_name="Dt", last_name="D", account_id="A1", title="CFO", tags="dnc_all"),
            person(person_id="cp", first_name="Cp", last_name="E", account_id="A2", title="CFO", email="cp@rival.example"),
            person(person_id="pd", first_name="Pd", last_name="F", account_id="A3", title="CFO", email="pd@sub.example"),
            person(person_id="ld", first_name="Ld", last_name="G", account_id="A4", title="CFO", email="ld@deal.example",
                   phone="+1-312-555-0109")])
        res = self.build(export_ids=["A1", "A2", "A3", "A4"])
        p = self.people()
        self.assertEqual(p["ok"]["send_ok"], "yes")
        expect = {"sr": "title is not a buyer", "nt": "notes say do not contact", "dt": "tag dnc_all",
                  "cp": "relationship is competitor", "pd": "relationship is parent_decides",
                  "ld": "live deal"}
        for pid, why in expect.items():
            self.assertEqual(p[pid]["send_ok"], "no", pid)
            self.assertIn(why, p[pid]["send_block_reason"], pid)
        self.assertEqual(p["nt"]["status"], "do_not_contact")        # a do-not-contact note sets the status
        self.assertEqual(p["ld"]["call_ok"], "no")                   # calls stay with the deal owner too
        self.assertEqual(res["exported"], 1)
        left = {r["person_id"]: r["left_out_reason"] for r in read(self.ws / "book/export-left-out.csv")}
        self.assertEqual(sorted(left), sorted(expect))

    def test_opt_out_and_left_tags_differ(self):
        cfg = dict(CFG, dnc_tags=["opted_out", "dnc_all", "legal_hold"], left_tags=["moved"])
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="lh", first_name="Lh", last_name="A", account_id="A1", title="CFO", tags="legal_hold"),
            person(person_id="mv", first_name="Mv", last_name="B", account_id="A1", title="CFO", tags="moved")])
        self.build()
        p = self.people()
        self.assertEqual(p["lh"]["status"], "do_not_contact")                # a custom opt-out tag from config
        self.assertEqual(p["mv"]["status"], "active")                        # moved never means do-not-contact
        for pid in ("lh", "mv"):
            self.assertEqual(p[pid]["send_ok"], "no", pid)
            self.assertEqual(p[pid]["call_ok"], "no", pid)
        self.assertIn("may have left", p["mv"]["send_block_reason"])

    def test_followup_gate_skips_only_the_sequence_rule(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="sq", first_name="Sq", last_name="A", account_id="A1", title="CFO", sequence="seq-1"),
            person(person_id="new", first_name="New", last_name="B", account_id="A1", title="CFO"),
            person(person_id="bad", first_name="Bad", last_name="C", account_id="A1", title="CFO", sequence="seq-1",
                   email_status="catch_all")])
        self.build()
        p = self.people()
        self.assertEqual((p["sq"]["send_ok"], p["sq"]["followup_ok"]), ("no", "yes"))
        self.assertEqual((p["new"]["send_ok"], p["new"]["followup_ok"]), ("yes", "no"))
        self.assertIn("not in a sequence", p["new"]["followup_block_reason"])
        self.assertEqual(p["bad"]["followup_ok"], "no")                      # every email check still applies
        self.assertIn("catch-all", p["bad"]["followup_block_reason"])

    def test_any_reply_at_the_account_stops_followups(self):
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "500", "country": "US", "tier": "P1", "status": "active"},
            {"account_id": "A2", "name": "Bolt", "domain": "bolt.example", "employees": "500", "country": "US", "tier": "P1", "status": "active"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="r", first_name="Re", last_name="A", account_id="A1", title="CFO", sequence="seq-1", tags="replied"),
            person(person_id="peer", first_name="Pe", last_name="B", account_id="A1", title="Controller", sequence="seq-1"),
            person(person_id="other", first_name="Ot", last_name="C", account_id="A2", title="CFO", sequence="seq-1",
                   email="ot.c@bolt.example")])
        self.build()
        p = self.people()
        self.assertEqual(p["r"]["followup_ok"], "no")
        self.assertIn("replied", p["r"]["followup_block_reason"])
        self.assertEqual(p["peer"]["followup_ok"], "no")
        self.assertIn("someone at this account replied", p["peer"]["followup_block_reason"])
        self.assertEqual(p["other"]["followup_ok"], "yes")

    def test_reads_excel_csv_with_bom_and_comma_numbers(self):
        path = self.ws / "input/accounts.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=ACCTS, lineterminator="\n")
            w.writeheader()
            w.writerow({"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "1,200", "tier": "P1"})
            w.writerow({"account_id": "A2", "name": "Tiny", "domain": "tiny.example", "employees": "1,50"})
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="ok", first_name="Ok", last_name="A", account_id="A1", title="CFO", email_score="1,00")])
        self.build()
        a = self.accounts()
        self.assertEqual(a["A1"]["strategy"], "priority")
        self.assertEqual(a["A2"]["strategy"], "hold")                # 150 is below the 200 floor
        self.assertEqual(self.people()["ok"]["send_ok"], "yes")

    def test_export_unknown_account_id_is_an_error(self):
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="ok", first_name="Ok", last_name="A", account_id="A1", title="CFO")])
        with self.assertRaisesRegex(ValueError, "not in the book: ZZ9"):
            self.build(export_ids=["A1", "ZZ9"])

    def test_refuses_to_write_into_input(self):
        write(self.ws / "input/people.csv", PEOPLE, [person(person_id="p1", first_name="A", last_name="B", account_id="A1")])
        with self.assertRaises(ValueError):
            book.build(self.ws, self.ws / "input", "2026-10-20")


class StrategyTests(Base):
    def setUp(self):
        super().setUp()
        accts = [
            {"account_id": "A1", "name": "Override", "domain": "a1.example", "employees": "500", "tier": "P1", "country": "US"},
            {"account_id": "A2", "name": "Rival", "domain": "a2.example", "employees": "500", "relationship": "competitor"},
            {"account_id": "A3", "name": "Parent", "domain": "a3.example", "employees": "500", "relationship": "parent_decides"},
            {"account_id": "A4", "name": "Small", "domain": "a4.example", "employees": "50"},
            {"account_id": "A5", "name": "Deal", "domain": "a5.example", "employees": "500", "status": "live_deal", "tier": "P1"},
            {"account_id": "A6", "name": "Signal", "domain": "a6.example", "employees": "500"},
            {"account_id": "A7", "name": "Tier", "domain": "a7.example", "employees": "500", "tier": "P2"},
            {"account_id": "A8", "name": "Plain", "domain": "a8.example", "employees": "500", "tier": "P3"},
            {"account_id": "A9", "name": "Replied", "domain": "a9.example", "employees": "500", "status": "live_deal"},
        ]
        write(self.ws / "input/accounts.csv", ACCTS, accts)
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="r1", first_name="R", last_name="One", account_id="A9", email="r@a9.example", tags="past_reply")])
        write(self.ws / "signals/scored.csv", ["account_id", "playable", "top_type"],
              [{"account_id": "A6", "playable": "yes", "top_type": "new_leader"}])

    def test_ladder_first_match_wins(self):
        self.build()
        rows = read(self.ws / "book/accounts.csv")
        for r in rows:
            if r["account_id"] == "A1":
                r["strategy_override"] = "re-engage"
        write(self.ws / "book/accounts.csv", list(rows[0].keys()), rows)
        self.build()
        got = {k: v["strategy"] for k, v in self.accounts().items()}
        self.assertEqual(got, {"A1": "re-engage", "A2": "excluded", "A3": "hold", "A4": "hold", "A5": "live",
                               "A6": "signal", "A7": "priority", "A8": "automated", "A9": "live"})
        self.assertEqual(self.accounts()["A1"]["strategy_reason"], "manual override")
        self.assertEqual(self.accounts()["A1"]["pain_status"], "hypothesis")

    def test_live_deal_beats_a_past_reply_and_blocks_every_channel(self):
        # Oct 22 review probe: a live deal plus one past reply used to become re-engage.
        self.build()
        self.assertEqual(self.accounts()["A9"]["strategy"], "live")
        r1 = self.people()["r1"]
        self.assertEqual((r1["send_ok"], r1["call_ok"], r1["linkedin_ok"]), ("no", "no", "no"))
        self.assertIn("live deal", r1["call_block_reason"])

    def test_override_never_reopens_a_live_deal_or_an_out_of_icp_account(self):
        # Oct 22 check finding: a manual override switched off the live-deal and out-of-ICP blocks.
        self.build()
        rows = read(self.ws / "book/accounts.csv")
        for r in rows:
            if r["account_id"] in ("A9", "A4"):
                r["strategy_override"] = "priority"
        write(self.ws / "book/accounts.csv", list(rows[0].keys()), rows)
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="r1", first_name="R", last_name="One", account_id="A9", email="r@a9.example", tags="past_reply"),
            person(person_id="s1", first_name="S", last_name="One", account_id="A4", email="s@a4.example")])
        self.build()
        accts = self.accounts()
        self.assertEqual(accts["A9"]["strategy"], "live")
        self.assertEqual(accts["A4"]["strategy"], "hold")
        self.assertIn("override priority not applied", accts["A9"]["strategy_reason"])
        self.assertEqual(accts["A9"]["strategy_override"], "priority")
        for pid in ("r1", "s1"):
            p = self.people()[pid]
            self.assertEqual((p["send_ok"], p["call_ok"], p["linkedin_ok"]), ("no", "no", "no"), pid)

    def test_status_case_does_not_matter(self):
        rows_path = self.ws / "input/accounts.csv"
        rows = read(rows_path)
        for r in rows:
            if r["account_id"] == "A9":
                r["status"] = "Live_Deal"
        write(rows_path, list(rows[0].keys()), rows)
        self.build()
        self.assertEqual(self.accounts()["A9"]["strategy"], "live")

    def test_readiness_and_lanes(self):
        write(self.ws / "input/accounts.csv", ACCTS, [{"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "500"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="A", account_id="A1", title="CFO"),
            person(person_id="p2", first_name="Bo", last_name="B", account_id="A1", title="Controller", email_status="risky")])
        self.build()
        a = self.accounts()["A1"]
        self.assertEqual(a["readiness"], "enrich")
        self.assertEqual(a["lanes_covered"], "finance")
        self.assertEqual(a["lanes_missing"], "tech")


UPDATE_COLS = ["account_id", "crm_id", "status", "owner", "relationship", "reason"]


class AccountUpdateTests(Base):
    """input/account-updates.csv comes from crm-sync's to-book-accounts.csv."""

    def setUp(self):
        super().setUp()
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Acme", "domain": "acme.example", "employees": "500", "country": "US",
             "tier": "P1", "status": "active", "crm_id": "CA1"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="p1", first_name="Ana", last_name="Lee", account_id="A1", title="CFO", phone="+1-312-555-0101")])

    def test_open_deal_from_the_crm_sets_live_deal_even_over_an_edit(self):
        self.build()
        rows = read(self.ws / "book/accounts.csv")
        rows[0]["status"] = "active"   # the user's own value in the book
        write(self.ws / "book/accounts.csv", list(rows[0].keys()), rows)
        write(self.ws / "input/account-updates.csv", UPDATE_COLS,
              [{"crm_id": "CA1", "status": "live_deal", "reason": "open opportunity O-1 (stage Demo)"}])
        self.build("2026-10-21")
        a = self.accounts()["A1"]
        self.assertEqual((a["status"], a["strategy"]), ("live_deal", "live"))
        self.assertEqual(self.people()["p1"]["call_ok"], "no")

    def test_owner_and_relationship_updates_apply_as_source_values(self):
        write(self.ws / "input/account-updates.csv", UPDATE_COLS,
              [{"account_id": "A1", "owner": "jordan", "relationship": "customer", "reason": "CRM account record"}])
        self.build()
        a = self.accounts()["A1"]
        self.assertEqual((a["owner"], a["relationship"], a["strategy"]), ("jordan", "customer", "excluded"))

    def test_update_for_an_unknown_account_is_a_warning(self):
        write(self.ws / "input/account-updates.csv", UPDATE_COLS, [{"crm_id": "NOPE", "status": "live_deal"}])
        result = self.build()
        self.assertTrue(any("NOPE" in w for w in result["warnings"]))


class RankTests(Base):
    def test_sticky_list_reports_challengers(self):
        accts = [{"account_id": f"A{i}", "name": f"Co{i}", "domain": f"a{i}.example", "employees": "500",
                  "tier": t} for i, t in ((1, "P1"), (2, "P2"), (3, "P3"))]
        accts.append({"account_id": "A4", "name": "Rival", "domain": "a4.example", "employees": "500",
                      "tier": "P1", "relationship": "competitor"})
        write(self.ws / "input/accounts.csv", ACCTS, accts)
        write(self.ws / "input/people.csv", PEOPLE, [])
        write(self.ws / "input/researched.csv", PEOPLE, [person(person_id="x", first_name="X", last_name="Y", account_id="A3", email="x@a3.example")])
        self.build()
        first = rank.rank_accounts(self.ws, "2026-10-20")
        self.assertEqual(first["effective"], ["A1", "A2"])
        self.assertFalse(first["frozen"])
        # A3 gets much stronger; the list stays, A3 is reported as a challenger
        rows = read(self.ws / "book/accounts.csv")
        for r in rows:
            if r["account_id"] == "A3":
                r["tier"] = "P1"
        write(self.ws / "book/accounts.csv", list(rows[0].keys()), rows)
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id=f"q{i}", first_name=f"Q{i}", last_name="Z", account_id="A3", email=f"q{i}@a3.example",
                   title=t) for i, t in enumerate(["CFO", "Controller", "Head of IT"])])
        self.build()
        second = rank.rank_accounts(self.ws, "2026-10-21")
        self.assertTrue(second["frozen"])
        self.assertEqual(second["effective"], ["A1", "A2"])
        self.assertIn("A3", second["challengers"])
        self.assertNotIn("A4", second["challengers"])  # competitors are never ranked
        top = json.loads((self.ws / "book/top.json").read_text())
        top["overrides"]["add"] = ["A3"]
        top["overrides"]["remove"] = ["A2"]
        (self.ws / "book/top.json").write_text(json.dumps(top))
        third = rank.rank_accounts(self.ws, "2026-10-22")
        self.assertEqual(third["effective"], ["A1", "A3"])
        reset = rank.rank_accounts(self.ws, "2026-10-22", reset=True)
        self.assertEqual(reset["effective"][0], "A3")


    def test_live_deals_and_user_relationships_are_never_ranked(self):
        cfg = dict(CFG, ranking={"top_n": 5, "never_rank_relationships": ["reseller"]})
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Acme", "domain": "a1.example", "employees": "500", "tier": "P1"},
            {"account_id": "A2", "name": "Deal", "domain": "a2.example", "employees": "500", "tier": "P1",
             "status": "live_deal"},
            {"account_id": "A3", "name": "Resell", "domain": "a3.example", "employees": "500", "tier": "P1",
             "relationship": "reseller"},
            {"account_id": "A4", "name": "Rival", "domain": "a4.example", "employees": "500", "tier": "P1",
             "relationship": "competitor"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="x", first_name="X", last_name="Y", account_id="A1", email="x@a1.example")])
        self.build()
        res = rank.rank_accounts(self.ws, "2026-10-20")
        self.assertEqual(res["effective"], ["A1"])   # live deal, user-excluded and ICP-excluded are all out

class FitRankingAndReadinessTests(Base):
    """Oct 22 review: ranking ignored ICP fit, and 'ready' did not need a decision maker."""

    def test_great_fit_outranks_a_well_staffed_poor_fit(self):
        cfg = dict(CFG, icp={"size": {"min": 200, "max": 5000, "sweet_min": 300, "sweet_max": 1000}},
                   segments=[{"id": "core", "industries": ["logistics"], "size_min": 300, "size_max": 1000}],
                   scoring={"account": {"sweet_spot": 3, "in_band": 1, "segment_match": 1}},
                   ranking={"top_n": 1})
        (self.ws / "gtm.json").write_text(json.dumps(cfg))
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Great fit", "domain": "a1.example", "employees": "600",
             "industry": "logistics", "country": "US", "tier": "P2"},
            {"account_id": "A2", "name": "Poor fit", "domain": "a2.example", "employees": "4500",
             "industry": "retail", "country": "US", "tier": "P2"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="g1", first_name="G", last_name="One", account_id="A1", email="g1@a1.example", title="CFO")]
            + [person(person_id=f"p{i}", first_name=f"P{i}", last_name="Two", account_id="A2",
                      email=f"p{i}@a2.example", title=t) for i, t in enumerate(["CFO", "Controller", "Head of IT"])])
        self.build()
        res = rank.rank_accounts(self.ws, "2026-10-20")
        self.assertEqual(res["effective"], ["A1"])
        report = (self.ws / "book/top-report.md").read_text()
        self.assertIn("ICP fit", report)

    def test_ready_needs_a_send_ready_decision_maker(self):
        write(self.ws / "input/accounts.csv", ACCTS, [
            {"account_id": "A1", "name": "Champions only", "domain": "acme.example", "employees": "500", "country": "US"}])
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="c1", first_name="Cat", last_name="One", account_id="A1", title="Controller"),
            person(person_id="c2", first_name="Cal", last_name="Two", account_id="A1", title="Controller")])
        self.build()
        self.assertEqual(self.accounts()["A1"]["readiness"], "enrich")
        write(self.ws / "input/people.csv", PEOPLE, [
            person(person_id="c1", first_name="Cat", last_name="One", account_id="A1", title="Controller"),
            person(person_id="d1", first_name="Dee", last_name="Three", account_id="A1", title="CFO")])
        self.build("2026-10-21")
        self.assertEqual(self.accounts()["A1"]["readiness"], "ready")


class ExampleTests(unittest.TestCase):
    def test_example_rebuild_matches_its_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "gtm"
            shutil.copytree(SKILL / "assets/example", ws)
            res = book.build(ws, ws / "book", "2026-10-20", export_ids=["A01", "A02"])
            p = {r["person_id"]: r for r in read(ws / "book/people.csv")}
            self.assertEqual(p["p02"]["title"], "Corporate Controller and FP&A lead")
            self.assertTrue(p["p02"]["notes"].startswith("2026-10-20: "))
            self.assertEqual(p["p04"]["phone"], "+1-617-555-0144")
            self.assertEqual(p["p12"]["status"], "booked")
            self.assertEqual(p["p13"]["status"], "do_not_contact")
            self.assertEqual(p["p14"]["timezone_source"], "manual")
            self.assertEqual(p["p-manual-1"]["source"], "manual")
            self.assertIn("p17", p)
            self.assertEqual(res["exported"], 3)
            left = {r["person_id"]: r["left_out_reason"] for r in read(ws / "book/export-left-out.csv")}
            self.assertEqual(sorted(left), ["p03", "p05", "p06"])
            self.assertIn("title is not a buyer", left["p06"])
            # a second rebuild changes nothing you typed
            book.build(ws, ws / "book", "2026-10-21")
            p2 = {r["person_id"]: r for r in read(ws / "book/people.csv")}
            self.assertEqual(p2["p02"]["title"], "Corporate Controller and FP&A lead")
            self.assertEqual(p2["p12"]["status"], "booked")
            self.assertEqual(p2["p14"]["timezone_source"], "manual")
            strat = {r["account_id"]: r["strategy"] for r in read(ws / "book/accounts.csv")}
            self.assertEqual(strat, {"A01": "priority", "A02": "priority", "A03": "live", "A04": "hold", "A05": "hold",
                                     "A06": "excluded", "A07": "re-engage", "A08": "signal", "A09": "priority",
                                     "A10": "automated"})
            fixes = read(ws / "book/fixes.csv")
            self.assertIn(("p02", "title"), {(f["person_id"], f["field"]) for f in fixes})


if __name__ == "__main__":
    unittest.main()
