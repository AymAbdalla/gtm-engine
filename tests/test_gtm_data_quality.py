"""Rule tests for the aym-gtm data-quality scripts, using made-up data only."""
import csv
import importlib.util
import json
from datetime import date
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/data-quality"
EXAMPLE = SKILL / "assets/example"
TODAY = date(2026, 10, 20)


def load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


clean = load("clean_list")
verify = load("verify_split")
audit = load("audit_crm")


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def probe_person(pid, first, last, title, email, phone, linkedin):
    return {"person_id": pid, "account_id": "A01", "first_name": first, "last_name": last, "title": title,
            "email": email, "email_status": "verified", "email_score": "95", "phone": phone,
            "linkedin_url": linkedin, "country": "US", "timezone": "America/Chicago", "status": "active",
            "last_touch_date": "", "sequence": "", "tags": "", "notes": "", "crm_id": "", "source": "crm"}


class MatchingProbeTests(unittest.TestCase):
    """Oct 22 review probes: a LinkedIn id link and a Rob/Robert pair with one phone."""

    @classmethod
    def setUpClass(cls):
        cfg = clean.load_config(EXAMPLE / "gtm.json")
        account = {"account_id": "A01", "name": "Brightmill Manufacturing", "domain": "brightmill.example",
                   "other_domains": "", "employees": "650", "industry": "manufacturing", "country": "US",
                   "tier": "P1", "relationship": "", "status": "active"}
        people = [
            probe_person("P01", "Dana", "Whitfield", "CFO", "dana.whitfield@brightmill.example",
                         "+1-312-555-0142", "https://www.linkedin.com/in/ACwAAB12xyz"),
            probe_person("P02", "Ann", "Lee", "VP Finance", "ann.lee@brightmill.example",
                         "+1-312-555-0150", "https://www.linkedin.com/sales/lead/ACwAAAxyz123,NAME_SEARCH,abc"),
            probe_person("P03", "Rob", "Whitfield", "Controller", "rob.w@brightmill.example",
                         "+1-312-555-0144", "https://linkedin.example/in/rob-whitfield"),
            probe_person("P04", "Robert", "Whitfield", "Controller", "robert.whitfield@brightmill.example",
                         "(312) 555-0144", "https://linkedin.example/in/rob-whitfield"),
        ]
        cls.out = clean.run(cfg, people, [account], TODAY)
        cls.where = {r["person_id"]: b for b, rs in cls.out.items() for r in rs}
        cls.row = {r["person_id"]: r for rs in cls.out.values() for r in rs}

    def test_linkedin_id_links_are_not_identity_doubt(self):
        self.assertNotIn("profile_mismatch", self.row["P01"]["defects"])
        self.assertNotIn("profile_mismatch", self.row["P02"]["defects"])
        self.assertNotEqual(self.where["P01"], "enrich")

    def test_a_name_slug_starting_with_ac_still_gets_the_name_check(self):
        # Oct 22 check finding: any slug starting "ac" skipped the name check.
        for slug in ("acosta-maria", "ackermann-john-12ab", "ACKERMANN-JOHN-12AB"):
            self.assertFalse(clean.linkedin_id_link(f"https://www.linkedin.com/in/{slug}"), slug)
        for slug in ("ACwAAB12xyz", "ACoAAA1b2C3d"):
            self.assertTrue(clean.linkedin_id_link(f"https://www.linkedin.com/in/{slug}"), slug)

    def test_same_phone_and_last_name_go_to_review(self):
        self.assertEqual(self.where["P04"], "review")
        self.assertIn("same phone", self.row["P04"]["reason"])
        self.assertNotEqual(self.where["P03"], "review")


class CleanListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = clean.load_config(EXAMPLE / "gtm.json")
        _, people = clean.read_csv(EXAMPLE / "input/people.csv")
        _, accounts = clean.read_csv(EXAMPLE / "input/accounts.csv")
        cls.out = clean.run(cls.cfg, people, accounts, TODAY)
        cls.where = {r["person_id"]: b for b, rs in cls.out.items() for r in rs}
        cls.row = {r["person_id"]: r for rs in cls.out.values() for r in rs}

    def test_every_person_lands_once(self):
        with open(EXAMPLE / "input/people.csv", encoding="utf-8") as fh:
            ids = [r["person_id"] for r in csv.DictReader(fh)]
        self.assertEqual(sorted(ids), sorted(self.where))
        self.assertEqual(len(ids), sum(len(v) for v in self.out.values()))

    def test_do_not_contact_wins(self):
        self.assertEqual(self.where["P19"], "quarantine")  # status do_not_contact
        self.assertEqual(self.where["P27"], "quarantine")  # left
        self.assertEqual(self.where["P39"], "quarantine")  # booked
        self.assertEqual(self.where["P20"], "quarantine")  # notes ask not to be contacted
        self.assertIn("do_not_contact", self.row["P20"]["reason"])

    def test_account_screens(self):
        self.assertIn("below the size floor", self.row["P23"]["reason"])
        self.assertIn("competitor", self.row["P24"]["reason"])
        self.assertIn("customer", self.row["P28"]["reason"])
        self.assertIn("excluded industry", self.row["P25"]["reason"])

    def test_do_not_contact_beats_a_duplicate_row(self):
        # P06 and P10 share an email. If the second row is do_not_contact, neither may reach ready.
        _, people = clean.read_csv(EXAMPLE / "input/people.csv")
        _, accounts = clean.read_csv(EXAMPLE / "input/accounts.csv")
        people = [dict(p, status="do_not_contact") if p["person_id"] == "P10" else p for p in people]
        out = clean.run(self.cfg, people, accounts, TODAY)
        where = {r["person_id"]: b for b, rs in out.items() for r in rs}
        reason = {r["person_id"]: r["reason"] for rs in out.values() for r in rs}
        self.assertEqual(where["P10"], "quarantine")
        self.assertEqual(where["P06"], "quarantine")
        self.assertIn("linked record P10", reason["P06"])
        # A dnc tag or note on either row links the same way.
        for change in ({"tags": "opted_out"}, {"notes": "Please remove me"}):
            people2 = [dict(p, **change) if p["person_id"] == "P10" else p
                       for p in clean.read_csv(EXAMPLE / "input/people.csv")[1]]
            out2 = clean.run(self.cfg, people2, accounts, TODAY)
            ready = {r["person_id"] for r in out2["ready"] + out2["later"]}
            self.assertNotIn("P06", ready, change)

    def test_linked_stops_say_the_real_reason(self):
        _, accounts = clean.read_csv(EXAMPLE / "input/accounts.csv")
        base = clean.read_csv(EXAMPLE / "input/people.csv")[1]

        def run_with(change):
            people = [dict(p, **change) if p["person_id"] == "P10" else p for p in base]
            out = clean.run(self.cfg, people, accounts, TODAY)
            where = {r["person_id"]: b for b, rs in out.items() for r in rs}
            reason = {r["person_id"]: r["reason"] for rs in out.values() for r in rs}
            return where["P06"], reason["P06"]

        bucket, reason = run_with({"status": "left"})
        self.assertEqual(bucket, "quarantine")
        self.assertIn("linked record P10: person status is left", reason)
        self.assertNotIn("do-not-contact", reason)
        bucket, reason = run_with({"tags": "moved"})
        self.assertEqual(bucket, "quarantine")
        self.assertIn("may have left", reason)
        for status in ("booked", "hold"):
            bucket, reason = run_with({"status": status})
            self.assertEqual(bucket, "review", status)          # a stale booked/hold row only asks for a check
            self.assertIn(f"person status is {status}", reason)

    def test_duplicate_rows_with_same_id_share_a_stop(self):
        _, accounts = clean.read_csv(EXAMPLE / "input/accounts.csv")
        people = clean.read_csv(EXAMPLE / "input/people.csv")[1]
        p06 = next(p for p in people if p["person_id"] == "P06")
        people = people + [dict(p06, email="", tags="opted_out")]   # same person_id, second row opted out
        out = clean.run(self.cfg, people, accounts, TODAY)
        ready = [r for r in out["ready"] + out["later"] if r["person_id"] == "P06"]
        self.assertEqual(ready, [])

    def test_shared_keys_drive_screens(self):
        cfg = clean.load_config(EXAMPLE / "gtm.json")
        self.assertNotIn("quarantine_status", cfg["clean"])
        self.assertNotIn("freemail_domains", cfg["clean"])
        account = {"account_id": "A01", "domain": "brightmill.example", "employees": "1,200",
                   "industry": "manufacturing", "country": "US"}
        person = {"person_id": "X", "title": "Controller", "status": "active",
                  "email": "x@brightmill.example", "email_status": "verified", "tags": "phone_failed",
                  "phone": "+1-312-555-0177"}
        bucket, reason, extras = clean.classify(person, account, cfg, TODAY)
        self.assertIn("dnc_phone", extras["defects"])          # phone_failed blocks calls
        self.assertNotIn("phone", extras["channels"].split(";"))
        self.assertEqual(clean.size_band(account, cfg), "band")  # "1,200" parses
        parent = dict(account, relationship="parent_decides")
        self.assertEqual(clean.classify(dict(person, tags=""), parent, cfg, TODAY)[0], "quarantine")

    def test_bom_files_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            (ws / "input").mkdir(parents=True)
            for name in ("people.csv", "accounts.csv"):
                text = (EXAMPLE / "input" / name).read_text(encoding="utf-8")
                (ws / "input" / name).write_text("\ufeff" + text, encoding="utf-8")
            cfg_text = (EXAMPLE / "gtm.json").read_text(encoding="utf-8")
            (ws / "gtm.json").write_text("\ufeff" + cfg_text, encoding="utf-8")
            clean.main(["--workspace", str(ws), "--out", str(Path(tmp) / "o"), "--today", "2026-10-20"])
            self.assertTrue(rows(Path(tmp) / "o" / "ready.csv"))

    def test_title_ladder(self):
        self.assertEqual(self.where["P08"], "quarantine")  # sales rep
        self.assertEqual(self.where["P34"], "quarantine")  # intern beats the finance word
        self.assertEqual(self.where["P33"], "quarantine")  # no persona
        self.assertEqual(self.where["P07"], "review")      # founder, no persona
        self.assertEqual(self.where["P37"], "review")      # advisor
        self.assertEqual(self.where["P18"], "enrich")      # no title

    def test_not_buyer_beats_persona(self):
        cfg = self.cfg
        person = {"person_id": "X", "title": "Accounts Payable Intern", "status": "active",
                  "email": "x@brightmill.example", "email_status": "verified"}
        account = {"account_id": "A01", "domain": "brightmill.example", "employees": "650",
                   "industry": "manufacturing", "country": "US"}
        bucket, reason, _ = clean.classify(person, account, cfg, TODAY)
        self.assertEqual(bucket, "quarantine")
        self.assertIn("never a buyer", reason)

    def test_region_rule_exempts_senior_titles(self):
        self.assertEqual(self.where["P12"], "quarantine")
        self.assertIn("another region", self.row["P12"]["reason"])
        self.assertEqual(self.where["P13"], "ready")

    def test_identity_doubt_goes_to_enrich(self):
        for pid in ("P17", "P29", "P30", "P31", "P09"):
            self.assertEqual(self.where[pid], "enrich", pid)
        self.assertIn("profile_mismatch", self.row["P17"]["defects"])
        self.assertIn("personal_email", self.row["P09"]["defects"])

    def test_no_usable_channel_goes_to_enrich(self):
        self.assertEqual(self.where["P14"], "enrich")  # invalid email, toll-free phone
        self.assertEqual(self.where["P21"], "enrich")  # bounced email, no phone

    def test_dnc_phone_zeroes_phone_points(self):
        row = self.row["P06"]
        self.assertEqual(self.where["P06"], "ready")
        self.assertNotIn("phone", row["channels"].split(";"))
        self.assertLess(int(row["score"]), 0)

    def test_duplicates_and_missing_account_go_to_review(self):
        self.assertIn("same email", self.row["P10"]["reason"])
        self.assertIn("same name", self.row["P36"]["reason"])
        self.assertIn("not found", self.row["P35"]["reason"])

    def test_cap_per_account_and_ranking(self):
        ready_a01 = [r["person_id"] for r in self.out["ready"] if r["account_id"] == "A01"]
        self.assertEqual(ready_a01, ["P01", "P04", "P02"])
        self.assertEqual(sorted(r["person_id"] for r in self.out["later"]), ["P03", "P05"])
        scores = [int(r["score"]) for r in self.out["ready"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_score_detail_adds_up(self):
        for row in self.out["ready"] + self.out["later"]:
            parts = [float(p.rsplit(" ", 1)[1]) for p in row["score_detail"].split("; ")]
            self.assertEqual(sum(parts), float(row["score"]), row["person_id"])
            self.assertTrue(row["score_detail"].startswith("phone "), row["score_detail"])

    def test_phone_types(self):
        cases = {"+1-312-555-0142": "direct", "+1-312-555-0100": "switchboard",
                 "1-800-555-0190": "toll_free", "+44 20 5550 0142": "international",
                 "555-01": "malformed", "": "none", "312 555 0142 ext 12": "direct",
                 "call me": "malformed"}
        for raw, expected in cases.items():
            self.assertEqual(clean.phone_type(raw, self.cfg), expected, raw)

    def test_refuses_to_overwrite_inputs_and_needs_personas(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(p.name for p in (EXAMPLE / "input").iterdir())
            with self.assertRaisesRegex(SystemExit, "input folder"):
                clean.main(["--workspace", str(EXAMPLE), "--out", str(EXAMPLE / "input"),
                            "--today", "2026-10-20"])
            with self.assertRaisesRegex(SystemExit, "input folder"):
                verify.main(["--list", str(EXAMPLE / "input/people.csv"), "--channel", "email",
                             "--verification", str(EXAMPLE / "input/verification.csv"),
                             "--out", str(EXAMPLE / "input")])
            with self.assertRaisesRegex(SystemExit, "input folder"):
                audit.main(["audit", "--workspace", str(EXAMPLE), "--out", str(EXAMPLE / "input")])
            self.assertEqual(before, sorted(p.name for p in (EXAMPLE / "input").iterdir()))
            bare = Path(tmp) / "gtm.json"
            bare.write_text(json.dumps({"icp": {}}))
            with self.assertRaisesRegex(SystemExit, "personas"):
                clean.load_config(bare)

    def test_cli_writes_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean.main(["--workspace", str(EXAMPLE), "--out", tmp, "--today", "2026-10-20"])
            for name in ("ready", "later", "review", "enrich", "quarantine"):
                self.assertTrue((Path(tmp) / f"{name}.csv").exists(), name)
            self.assertIn("A vendor with no record", (Path(tmp) / "report.md").read_text())


class VerifySplitTests(unittest.TestCase):
    def setUp(self):
        self.cfg = verify.load_config(EXAMPLE / "gtm.json")
        self.person = {"person_id": "P1", "email": "a@x.example", "status": "active", "tags": ""}

    def decide(self, results, channel="email", person=None):
        return verify.decide(person or self.person, results, channel, self.cfg)

    def test_channel_inference_defaults_to_strictest(self):
        self.assertEqual(verify.infer_channel("ready.csv")[0], "call")
        self.assertEqual(verify.infer_channel("email-batch.csv")[0], "email")
        self.assertEqual(verify.infer_channel("dial-list.csv")[0], "call")
        self.assertEqual(verify.infer_channel("linkedin-week.csv")[0], "linkedin")

    def test_email_result_never_clears_a_call(self):
        ok, _, _, reason = self.decide([{"channel": "email", "verdict": "valid", "score": "99"}], "call")
        self.assertFalse(ok)
        self.assertIn("never clears a call", reason)

    def test_fail_closed_cases(self):
        self.assertFalse(self.decide([])[0])
        self.assertFalse(self.decide([{"channel": "email", "verdict": "catch_all", "score": "90"}])[0])
        self.assertFalse(self.decide([{"channel": "email", "verdict": "valid", "score": ""}])[0])
        self.assertFalse(self.decide([{"channel": "email", "verdict": "valid", "score": "79"}])[0])
        ok, _, _, reason = self.decide([{"channel": "email", "verdict": "valid", "score": "90"},
                                        {"channel": "email", "verdict": "invalid", "score": "20"}])
        self.assertFalse(ok)
        self.assertIn("conflicting", reason)
        ok, _, _, reason = self.decide([{"channel": "email", "email": "b@x.example",
                                         "verdict": "valid", "score": "95"}])
        self.assertFalse(ok)
        self.assertIn("different email", reason)

    def test_pass_and_blocks(self):
        good = [{"channel": "email", "email": "a@x.example", "verdict": "valid", "score": "90"}]
        self.assertTrue(self.decide(good)[0])
        blocked = dict(self.person, status="do_not_contact")
        self.assertFalse(self.decide(good, person=blocked)[0])
        dnc = dict(self.person, tags="dnc_phone")
        phone = [{"channel": "phone", "verdict": "valid", "score": "95"}]
        self.assertFalse(self.decide(phone, "call", dnc)[0])
        self.assertTrue(self.decide([{"channel": "linkedin", "verdict": "match", "score": ""}], "linkedin")[0])

    def test_opted_out_and_note_block_every_channel(self):
        good = [{"channel": "email", "email": "a@x.example", "verdict": "valid", "score": "90"}]
        self.assertFalse(self.decide(good, person=dict(self.person, tags="opted_out"))[0])
        self.assertFalse(self.decide(good, person=dict(self.person, notes="remove me please"))[0])
        bounced = dict(self.person, tags="bounced")
        self.assertFalse(self.decide(good, person=bounced)[0])
        phone = [{"channel": "phone", "verdict": "valid", "score": "95"}]
        self.assertTrue(self.decide(phone, "call", bounced)[0])  # a bounce only blocks email
        self.assertFalse(self.decide(phone, "call", dict(self.person, tags="phone_failed"))[0])

    def test_example_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean.main(["--workspace", str(EXAMPLE), "--out", tmp, "--today", "2026-10-20"])
            out = Path(tmp) / "v"
            verify.main(["--list", str(Path(tmp) / "ready.csv"), "--channel", "email",
                         "--verification", str(EXAMPLE / "input/verification.csv"),
                         "--config", str(EXAMPLE / "gtm.json"), "--out", str(out)])
            safe = sorted(r["person_id"] for r in rows(out / "safe.csv"))
            self.assertEqual(safe, ["P01", "P04", "P06", "P11"])  # P06 matched by email only


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = audit.load_config(EXAMPLE / "gtm.json")
        cls.accounts = audit.read_csv(EXAMPLE / "input/accounts.csv")
        cls.people = audit.read_csv(EXAMPLE / "input/people.csv")
        cls.sequences = audit.read_csv(EXAMPLE / "input/sequences.csv")
        cls.run_ = audit.Audit(cls.cfg, cls.accounts, cls.people, cls.sequences, TODAY)
        cls.summary = cls.run_.run()

    def test_health_formula(self):
        results = [{"ran": True, "weight": 3, "share": 0.25}, {"ran": True, "weight": 1, "share": 0.0},
                   {"ran": False, "weight": 5, "share": 1.0}]
        self.assertAlmostEqual(audit.health(results), round(100 * (1 - 3 * 0.5 / 4), 1))
        self.assertEqual(audit.grade(91), "A")
        self.assertEqual(audit.grade(59.9), "F")

    def test_fix_order_is_stops_first(self):
        steps = [f["step"] for f in self.run_.fixes]
        self.assertEqual(steps, sorted(steps))
        first = self.run_.fixes[0]
        self.assertEqual((first["record_id"], first["new_value"]), ("P20", "do_not_contact"))

    def test_expected_tickets(self):
        got = {(f["record_type"], f["record_id"], f["field"], f["new_value"]) for f in self.run_.fixes}
        self.assertIn(("sequence", "P19:seq-cfo-a", "status", "closed"), got)
        self.assertIn(("sequence", "P21:seq-ap-a", "status", "closed"), got)
        self.assertIn(("person", "P21", "email_status", "invalid"), got)
        self.assertIn(("account", "A06", "status", "hold"), got)
        self.assertIn(("sequence", "P02:seq-controller-a", "status", "closed"), got)
        self.assertIn(("account", "A12", "domain", "harborview-clinics.example"), got)
        self.assertIn(("person", "P05", "tags", ""), got)

    def test_merges_and_double_enrollment_are_never_tickets(self):
        self.assertFalse(any(f["record_id"] in ("A01", "A09", "A02", "A10") and f["field"] != "status"
                             for f in self.run_.fixes))
        issues = {(r["record_id"], r["issue"].split(" (")[0]) for r in self.run_.review}
        self.assertIn(("A01;A09", "safe merge"), issues)
        self.assertIn(("A02;A10", "possible duplicate"), issues)
        self.assertIn(("P11", "enrolled in more than one active sequence"), issues)
        self.assertIn(("P06", "re-entry candidate"), issues)

    def test_domain_rule_needs_enough_people(self):
        accounts = [{"account_id": "B1", "name": "B", "domain": "b.example", "status": "active"}]
        people = [{"person_id": f"Q{i}", "account_id": "B1", "status": "active",
                   "email": f"q{i}@other.example"} for i in range(2)]
        run_ = audit.Audit(self.cfg, accounts, people, None, TODAY)
        run_.run()
        self.assertFalse(any(f["field"] == "domain" for f in run_.fixes))
        self.assertEqual(len([r for r in run_.review if r["issue"].startswith("email domain")]), 2)

    def test_bounce_without_email_goes_to_review(self):
        people = [{"person_id": "Q1", "account_id": "B1", "status": "active", "tags": "bounced", "email": ""}]
        run_ = audit.Audit(self.cfg, [], people, None, TODAY)
        run_.run()
        self.assertEqual(run_.fixes, [])
        self.assertIn("call outcome", run_.review[0]["evidence"])

    def test_opted_out_and_note_dnc_close_live_sequences(self):
        people = [
            {"person_id": "Q4", "account_id": "B1", "status": "active", "tags": "opted_out",
             "email": "q4@b.example", "email_status": "verified"},
            {"person_id": "Q20", "account_id": "B1", "status": "active", "tags": "",
             "notes": "Do not contact again", "email": "q20@b.example", "email_status": "verified"},
            {"person_id": "Q5", "account_id": "B1", "status": "active", "tags": "",
             "email": "q5@b.example", "email_status": "verified"},
        ]
        seqs = [{"person_id": pid, "sequence": "s1", "step": "1", "due_date": "2026-10-19", "status": "active"}
                for pid in ("Q4", "Q20", "Q5")]
        run_ = audit.Audit(self.cfg, [], people, seqs, TODAY)
        run_.run()
        got = {(f["step"], f["record_id"], f["field"], f["new_value"]) for f in run_.fixes}
        self.assertIn((1, "Q4:s1", "status", "closed"), got)
        self.assertIn((1, "Q20:s1", "status", "closed"), got)
        self.assertIn((1, "Q4", "status", "do_not_contact"), got)
        self.assertIn((1, "Q20", "status", "do_not_contact"), got)
        self.assertNotIn((1, "Q5:s1", "status", "closed"), got)

    def test_left_tag_suggests_left_not_do_not_contact(self):
        people = [{"person_id": "Q7", "account_id": "B1", "status": "active", "tags": "moved",
                   "email": "q7@b.example", "email_status": "verified"}]
        seqs = [{"person_id": "Q7", "sequence": "s1", "step": "2", "due_date": "2026-10-19", "status": "active"}]
        run_ = audit.Audit(self.cfg, [], people, seqs, TODAY)
        run_.run()
        got = {(f["record_id"], f["field"], f["new_value"]) for f in run_.fixes}
        self.assertIn(("Q7", "status", "left"), got)
        self.assertNotIn(("Q7", "status", "do_not_contact"), got)
        self.assertIn(("Q7:s1", "status", "closed"), got)

    def test_one_freemail_list_for_clean_and_audit(self):
        cfg_c = clean.load_config(EXAMPLE / "gtm.json")
        cfg_a = audit.load_config(EXAMPLE / "gtm.json")
        self.assertEqual(cfg_c["freemail_domains"], cfg_a["freemail_domains"])
        accounts = [{"account_id": "B1", "name": "B", "domain": "b.example", "status": "active"}]
        people = [{"person_id": "Q1", "account_id": "B1", "status": "active",
                   "email": "q1@freemail.example"}]
        run_ = audit.Audit(cfg_a, accounts, people, None, TODAY)
        run_.run()
        self.assertFalse([r for r in run_.review if r["record_id"] == "Q1"])

    def test_sequence_check_not_run_without_file(self):
        run_ = audit.Audit(self.cfg, self.accounts, self.people, None, TODAY)
        summary = run_.run()
        seq = [c for c in summary["checks"] if c["id"] == "sequences"][0]
        self.assertFalse(seq["ran"])

    def test_recheck_splits_ready_skip_drift(self):
        fixes = [dict(f) for f in self.run_.fixes]
        people = [dict(p) for p in self.people]
        accounts = [dict(a) for a in self.accounts]
        for p in people:
            if p["person_id"] == "P20":
                p["status"] = "do_not_contact"      # already done
        for a in accounts:
            if a["account_id"] == "A12":
                a["domain"] = "harborview-health.example"  # changed by someone else
        ready, skip, drift = audit.recheck(fixes, accounts, people, self.sequences)
        self.assertIn("P20", [f["record_id"] for f in skip])
        self.assertIn("A12", [f["record_id"] for f in drift])
        self.assertIn("A06", [f["record_id"] for f in ready])
        self.assertEqual(len(ready) + len(skip) + len(drift), len(fixes))

    def test_report_leads_with_scope_and_never_says_pass(self):
        text = audit.render(self.summary, self.run_.fixes, self.run_.review)
        self.assertLess(text.index("## Scope and limits"), text.index("## Verdict"))
        self.assertLess(text.index("## Verdict"), text.index("Health:"))
        self.assertIn(f"Read: {len(self.accounts)} accounts, {len(self.people)} people", text)
        self.assertIn("Checks run: 9 of 9", text)
        self.assertIn("Blockers found within scope", text)
        self.assertNotIn("passes", text.lower())
        found = [r for r in self.summary["checks"] if r["ran"] and r["affected"]]
        self.assertEqual(text.count("- Evidence:"), len(found))
        self.assertEqual(text.count("- Fix:"), len(found))
        self.assertEqual(text.count("- Verify:"), len(found))
        self.assertTrue(all(f["verify"] for f in self.run_.fixes))

    def test_clean_export_says_no_blockers_within_scope(self):
        acc = [{"account_id": "A1", "name": "Calm Co", "domain": "calm.example", "employees": "500",
                "industry": "logistics", "country": "US", "status": "active", "relationship": ""}]
        ppl = [{"person_id": "P1", "account_id": "A1", "first_name": "Ana", "last_name": "Ruiz",
                "title": "Controller", "email": "ana.ruiz@calm.example", "email_status": "verified",
                "phone": "+1-555-0101", "status": "active", "tags": "", "notes": "",
                "last_touch_date": "2026-10-15"}]
        run = audit.Audit(self.cfg, acc, ppl, None, TODAY)
        summary = run.run()
        text = audit.render(summary, run.fixes, run.review)
        self.assertEqual(summary["blockers"], 0)
        self.assertIn("No blockers found within scope. This is not a pass", text)
        self.assertIn("no sequences file, so sequence checks did not run", text)
        self.assertIn("Not run: ", text)

    def test_cli_audit_and_recheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit.main(["audit", "--workspace", str(EXAMPLE), "--sequences",
                        str(EXAMPLE / "input/sequences.csv"), "--out", tmp, "--today", "2026-10-20"])
            for name in ("audit.md", "audit.json", "fixes.csv", "review-queue.csv"):
                self.assertTrue((Path(tmp) / name).exists(), name)
            audit.main(["recheck", "--workspace", str(EXAMPLE), "--fixes", str(Path(tmp) / "fixes.csv"),
                        "--sequences", str(EXAMPLE / "input/sequences.csv"), "--out", str(Path(tmp) / "r")])
            self.assertEqual(len(rows(Path(tmp) / "r/fixes-ready.csv")), len(rows(Path(tmp) / "fixes.csv")))


if __name__ == "__main__":
    unittest.main()
