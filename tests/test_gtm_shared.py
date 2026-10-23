"""Shared rules across the aym-gtm skills: one ICP-fit rule, one example config.

The probe accounts come from the Oct 22 quality review: a retail account (industry not
on the ICP list), a government account (an excluded industry), a 9,000-person account
(above the 2,000 ceiling) and an account with blank size and industry. The expected
verdicts come from the example ICP in gtm.json, not from the code.
"""
import csv
import importlib.util
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GTM = ROOT / "plugins/aym-gtm/skills"
FIT_SKILLS = ("icp-define", "data-quality", "account-book", "signal-score")
EXAMPLE_CFG = GTM / "icp-define/assets/example/gtm.json"


def load(skill, script):
    spec = importlib.util.spec_from_file_location(f"{skill}_{script}".replace("-", "_"),
                                                  GTM / skill / "scripts" / f"{script}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def quiet(fn, argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(argv)


ACCOUNT_COLS = ["account_id", "name", "domain", "other_domains", "employees", "industry", "country",
                "tier", "relationship", "status", "owner", "crm_id", "notes"]
PEOPLE_COLS = ["person_id", "account_id", "first_name", "last_name", "title", "email", "email_status",
               "email_score", "phone", "linkedin_url", "country", "timezone", "status", "last_touch_date",
               "sequence", "tags", "notes", "crm_id", "source"]
PROBES = [
    # account_id, name, domain, employees, industry
    ("A1", "Goodco", "goodco.example", "600", "logistics"),
    ("A2", "Retailco", "retailco.example", "600", "retail"),
    ("A3", "Govco", "govco.example", "600", "government"),
    ("A4", "Hugeco", "hugeco.example", "9000", "logistics"),
    ("A5", "Blankco", "blankco.example", "", ""),
]


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def probe_workspace(root):
    shutil.copy(EXAMPLE_CFG, root / "gtm.json")
    accounts, people = [], []
    for i, (aid, name, dom, emp, ind) in enumerate(PROBES, 1):
        accounts.append({"account_id": aid, "name": name, "domain": dom, "employees": emp, "industry": ind,
                         "country": "US", "tier": "P1", "status": "active", "owner": "", "crm_id": f"C{aid}"})
        people.append({"person_id": f"P{i}", "account_id": aid, "first_name": f"First{i}",
                       "last_name": f"Last{i}", "title": "CFO", "email": f"f{i}@{dom}",
                       "email_status": "verified", "email_score": "95",
                       "phone": f"+1-312-555-01{10 + i}", "linkedin_url": f"https://linkedin.example/in/first{i}-last{i}",
                       "country": "US", "timezone": "America/Chicago", "status": "active", "crm_id": f"CP{i}",
                       "source": "crm"})
    write_csv(root / "input/accounts.csv", ACCOUNT_COLS, accounts)
    write_csv(root / "input/people.csv", PEOPLE_COLS, people)
    sig_cols = ["signal_id", "account_name", "domain", "type", "event_date", "summary", "source_url",
                "person_name", "person_title"]
    write_csv(root / "signals/raw/2026-10-20/news.csv", sig_cols,
              [{"signal_id": f"S{i}", "account_name": name, "domain": dom, "type": "funding",
                "event_date": "2026-10-10", "summary": f"{name} raised a round",
                "source_url": f"https://news.example/{i}"} for i, (_, name, dom, _, _) in enumerate(PROBES, 1)])


class SharedCopiesTests(unittest.TestCase):
    def test_fit_module_is_identical_in_every_skill(self):
        texts = {s: (GTM / s / "scripts/gtm_fit.py").read_bytes() for s in FIT_SKILLS}
        first = texts["icp-define"]
        for skill, text in texts.items():
            self.assertEqual(text, first, f"{skill}/scripts/gtm_fit.py differs from icp-define's copy")

    def test_example_config_is_identical_in_every_skill(self):
        copies = sorted(GTM.glob("*/assets/example/gtm.json"))
        self.assertEqual(len(copies), 10)
        first = EXAMPLE_CFG.read_bytes()
        for path in copies:
            self.assertEqual(path.read_bytes(), first, f"{path.relative_to(ROOT)} differs")


class OneFitVerdictTests(unittest.TestCase):
    """The same account gets the same ICP verdict in all four skills."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ws = Path(cls.tmp.name)
        probe_workspace(cls.ws)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_icp_define_marks_out_and_unknown(self):
        icp = load("icp-define", "icp_check")
        quiet(icp.main, ["--workspace", str(self.ws), "--out", str(self.ws / "icp")])
        got = {r["account_id"]: r["in_icp"] for r in read_csv(self.ws / "icp/accounts-icp.csv")}
        self.assertEqual(got, {"A1": "yes", "A2": "no", "A3": "no", "A4": "no", "A5": "unknown"})

    def test_data_quality_quarantines_out_and_enriches_unknown(self):
        dq = load("data-quality", "clean_list")
        quiet(dq.main, ["--workspace", str(self.ws), "--today", "2026-10-20", "--out", str(self.ws / "clean")])
        bucket = {}
        for name in ("ready", "later", "review", "enrich", "quarantine"):
            for r in read_csv(self.ws / f"clean/{name}.csv"):
                bucket[r["account_id"]] = name
        self.assertEqual(bucket, {"A1": "ready", "A2": "quarantine", "A3": "quarantine",
                                  "A4": "quarantine", "A5": "enrich"})

    def test_account_book_blocks_everyone_outside_or_unknown(self):
        ab = load("account-book", "build_book")
        quiet(ab.main, ["--workspace", str(self.ws), "--today", "2026-10-20", "--out", str(self.ws / "book")])
        send = {r["account_id"]: r["send_ok"] for r in read_csv(self.ws / "book/people.csv")}
        call = {r["account_id"]: r["call_ok"] for r in read_csv(self.ws / "book/people.csv")}
        self.assertEqual(send, {"A1": "yes", "A2": "no", "A3": "no", "A4": "no", "A5": "no"})
        self.assertEqual(call, {"A1": "yes", "A2": "no", "A3": "no", "A4": "no", "A5": "no"})

    def test_signal_score_holds_out_and_unknown(self):
        ss = load("signal-score", "score_signals")
        quiet(ss.main, ["--workspace", str(self.ws), "--today", "2026-10-20", "--out", str(self.ws / "signals/out")])
        rows = {r["account_id"]: r for r in read_csv(self.ws / "signals/out/scored.csv")}
        playable = {aid: r["playable"] for aid, r in rows.items()}
        self.assertEqual(playable, {"A1": "yes", "A2": "no", "A3": "no", "A4": "no", "A5": "no"})
        self.assertIn("excluded industry: government", rows["A3"]["why_not"])
        self.assertIn("enrich", rows["A5"]["why_not"])


class LiveDealChainTests(unittest.TestCase):
    """An open deal in the CRM stops outbound in every downstream skill (Oct 22 review)."""

    def test_open_crm_deal_reaches_book_play_and_plan(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            shutil.copy(EXAMPLE_CFG, ws / "gtm.json")
            write_csv(ws / "input/accounts.csv", ACCOUNT_COLS, [
                {"account_id": "A1", "name": "Dealco", "domain": "dealco.example", "employees": "600",
                 "industry": "logistics", "country": "US", "tier": "P1", "status": "active", "crm_id": "CA1"}])
            write_csv(ws / "input/people.csv", PEOPLE_COLS, [
                {"person_id": "P1", "account_id": "A1", "first_name": "Ann", "last_name": "Lee", "title": "CFO",
                 "email": "ann@dealco.example", "email_status": "verified", "email_score": "95",
                 "phone": "+1-312-555-0111", "linkedin_url": "https://linkedin.example/in/ann-lee",
                 "country": "US", "timezone": "America/Chicago", "status": "active", "crm_id": "C1",
                 "tags": "past_reply", "notes": "met at a conference", "source": "crm"}])
            seqs = (GTM / "play-build/assets/example/outreach/sequences.json").read_text()
            (ws / "outreach").mkdir()
            (ws / "outreach/sequences.json").write_text(seqs)
            write_csv(ws / "log/activity.csv", ["activity_id", "timestamp", "person_id", "account_id", "channel",
                                                "direction", "sequence", "step", "play_id", "angle", "opener",
                                                "outcome", "notes", "source"], [])
            ab = load("account-book", "build_book")
            quiet(ab.main, ["--workspace", str(ws), "--today", "2026-10-20"])
            self.assertEqual(read_csv(ws / "book/people.csv")[0]["call_ok"], "yes")   # before the deal opens

            write_csv(ws / "input/crm-export/people.csv",
                      ["crm_id", "first_name", "last_name", "title", "email", "status", "account_name", "account_domain"],
                      [{"crm_id": "C1", "first_name": "Ann", "last_name": "Lee", "title": "CFO",
                        "email": "ann@dealco.example", "status": "active", "account_name": "Dealco",
                        "account_domain": "dealco.example"}])
            write_csv(ws / "input/crm-export/opportunities.csv",
                      ["opportunity_id", "account_crm_id", "stage", "is_closed", "owner", "updated_at"],
                      [{"opportunity_id": "O-9", "account_crm_id": "CA1", "stage": "Discovery", "is_closed": "false",
                        "owner": "ae-1"}])
            cs = load("crm-sync", "sync_crm")
            quiet(cs.main, ["--workspace", str(ws), "--today", "2026-10-20"])
            shutil.copy(ws / "sync/to-book-accounts.csv", ws / "input/account-updates.csv")
            quiet(ab.main, ["--workspace", str(ws), "--today", "2026-10-21"])
            acct = read_csv(ws / "book/accounts.csv")[0]
            self.assertEqual((acct["status"], acct["strategy"]), ("live_deal", "live"))

            play = {"id": "blitz", "type": "blitz", "accounts": ["A1"], "sequence": "seq-trigger-finance",
                    "start": "2026-10-22", "end": "2026-11-30", "channel": "any", "daily_cap": 3}
            (ws / "plays/blitz").mkdir(parents=True)
            (ws / "plays/blitz/play.json").write_text(json.dumps(play))
            bp = load("play-build", "build_play")
            quiet(bp.main, ["--workspace", str(ws), "--play", str(ws / "plays/blitz/play.json"), "--today", "2026-10-21"])
            rows = read_csv(ws / "plays/blitz/enroll.csv")
            self.assertTrue(rows and all(r["drop_reason"] for r in rows), rows)

            dp = load("daily-plan", "plan_day")
            quiet(dp.main, ["--workspace", str(ws), "--today", "2026-10-21"])
            plan_rows = read_csv(ws / "plan/2026-10-21.csv")
            self.assertEqual([r for r in plan_rows if r.get("person_id") == "P1"], [])


class TechStackRuleTests(unittest.TestCase):
    """icp.technographics: a required tool keeps an account in; blank tech is unknown."""

    def test_required_tech_decides_fit_and_blank_is_unknown(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            cfg = json.loads(EXAMPLE_CFG.read_text())
            cfg["icp"]["technographics"] = {"required_any": ["netsuite", "sage intacct"], "excluded": ["sap"]}
            (ws / "gtm.json").write_text(json.dumps(cfg))
            base = {"employees": "600", "industry": "logistics", "country": "US", "status": "active"}
            rows = [dict(base, account_id="T1", name="Uses NetSuite", tech="NetSuite; Slack"),
                    dict(base, account_id="T2", name="Uses QuickBooks", tech="quickbooks"),
                    dict(base, account_id="T3", name="Uses SAP", tech="netsuite;sap"),
                    dict(base, account_id="T4", name="No tech data", tech="")]
            write_csv(ws / "input/accounts.csv", ACCOUNT_COLS + ["tech"], rows)
            icp = load("icp-define", "icp_check")
            quiet(icp.main, ["--workspace", str(ws), "--out", str(ws / "icp")])
            got = {r["account_id"]: (r["in_icp"], r["icp_reason"]) for r in read_csv(ws / "icp/accounts-icp.csv")}
        self.assertEqual(got["T1"][0], "yes")
        self.assertEqual(got["T2"], ("no", "uses none of the required tech"))
        self.assertEqual(got["T3"], ("no", "uses excluded tech: sap"))
        self.assertEqual(got["T4"][0], "unknown")
        self.assertIn("tech stack unknown", got["T4"][1])


class NotANumberTests(unittest.TestCase):
    """Oct 22 check finding: a "nan" headcount counted as in, and icp_check then crashed."""

    def test_nan_and_inf_headcounts_are_unknown(self):
        fit = load("icp-define", "gtm_fit")
        icp = {"size": {"min": 200, "max": 2000}}
        for bad in ("nan", "NaN", "inf", "-inf"):
            self.assertEqual(fit.fit({"employees": bad}, icp)[0], "unknown", bad)

    def test_icp_check_runs_on_a_nan_row(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "gtm.json").write_text(EXAMPLE_CFG.read_text())
            write_csv(ws / "input/accounts.csv", ACCOUNT_COLS, [
                {"account_id": "N1", "name": "Nan Co", "employees": "nan", "industry": "logistics",
                 "country": "US", "status": "active"}])
            icp = load("icp-define", "icp_check")
            quiet(icp.main, ["--workspace", str(ws), "--out", str(ws / "icp")])
            got = read_csv(ws / "icp/accounts-icp.csv")
        self.assertEqual(got[0]["in_icp"], "unknown")


if __name__ == "__main__":
    unittest.main()
