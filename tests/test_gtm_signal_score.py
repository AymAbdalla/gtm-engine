"""Rule checks for aym-gtm signal-score (score_signals.py) on made-up data."""
import contextlib
import datetime as dt
import io
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "aym-gtm" / "skills" / "signal-score"
EXAMPLE = SKILL / "assets" / "example"
spec = importlib.util.spec_from_file_location("score_signals", SKILL / "scripts" / "score_signals.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)

TODAY = dt.date(2026, 10, 20)
HEADER = "signal_id,account_name,domain,type,event_date,summary,source_url,person_name,person_title\n"


def digest(folder):
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(folder).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class DefaultExpiryTests(unittest.TestCase):
    """Defaults from the Oct 22 review: job posts expire after 60 days, intent after 30."""

    def test_hiring_and_intent_expiry_defaults(self):
        cfg = ss.load_config(None)
        self.assertEqual(cfg["types"]["hiring"]["expires_days"], 60)
        self.assertEqual(cfg["types"]["topic_intent"]["expires_days"], 30)
        example = json.loads((EXAMPLE / "gtm.json").read_text())["signals"]["types"]
        self.assertEqual((example["hiring"]["expires_days"], example["topic_intent"]["expires_days"]), (60, 30))


class FitQuadrantTests(unittest.TestCase):
    def test_out_of_icp_with_a_fresh_signal_is_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "gtm"
            shutil.copytree(EXAMPLE, ws)
            with (ws / "input/accounts.csv").open("a") as f:
                f.write("A012,Govco,govco.example,,600,government,US,P1,,active,,,\n")
            (ws / "signals/raw/2026-10-15/news-extra.csv").write_text(
                HEADER + "S090,Govco,govco.example,funding,2026-10-10,Closed a round,https://news.example/govco,,\n")
            rows = {r["account_id"]: r for r in ss.score(ws, TODAY)["scored"]}
        self.assertEqual(rows["A012"]["quadrant"], "verify")
        self.assertEqual(rows["A012"]["playable"], "no")


class ExampleWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ws = Path(cls.tmp.name) / "gtm"
        shutil.copytree(EXAMPLE, cls.ws)
        cls.raw_before = digest(cls.ws / "signals" / "raw")
        cls.result = ss.score(cls.ws, TODAY)
        cls.rows = {r["account_id"]: r for r in cls.result["scored"]}
        cls.trace = {t["signal_id"] + ":" + t["raw_file"]: t for t in cls.result["trace"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_counts(self):
        self.assertEqual(self.result["counts"], {"read": 18, "live": 12, "expired": 2, "unmatched": 1,
                                                 "skipped": 2, "duplicate": 1})

    def test_best_per_type_summed_with_recency(self):
        # new leader 22 days old (5 x 1.0); the hiring post is 80 days old, past the 60-day default
        self.assertEqual(self.rows["A001"]["score"], 5.0)
        self.assertEqual(self.rows["A001"]["top_type"], "new_leader")

    def test_thirty_day_boundary_keeps_full_weight(self):
        self.assertEqual(self.rows["A007"]["score"], 4.0)  # 2026-09-20 is exactly 30 days old

    def test_old_signal_gets_low_factor(self):
        self.assertEqual(self.rows["A009"]["score"], 4.6)  # funding 112 days (1.6) + intent (3.0)

    def test_expired_signal_does_not_score(self):
        expired = [t for t in self.result["trace"] if t["status"] == "expired"]
        self.assertEqual(sorted(t["signal_id"] for t in expired), ["S002", "S013"])
        self.assertEqual(self.rows["A004"]["score"], 3.0)  # only the intent signal counts

    def test_other_domain_and_legal_suffix_match(self):
        self.assertEqual(self.rows["A002"]["score"], 4.0)  # matched on other_domains
        s004 = [t for t in self.result["trace"] if t["signal_id"] == "S004"][0]
        self.assertEqual((s004["status"], s004["account_id"], s004["reason"]), ("live", "A007", "matched by name"))

    def test_unmatched_skipped_duplicate_reported(self):
        by_id = {}
        for t in self.result["trace"]:
            by_id.setdefault(t["signal_id"], []).append(t["status"])
        self.assertEqual(by_id["S003"], ["unmatched"])
        self.assertEqual(by_id["S018"], ["skipped"])  # no source link
        self.assertEqual(by_id["S019"], ["skipped"])  # unknown type
        self.assertEqual(sorted(by_id["S010"]), ["duplicate", "live"])

    def test_gate_blocks_hold_customer_live_deal_and_weight_zero(self):
        self.assertEqual((self.rows["A005"]["playable"], self.rows["A005"]["why_not"]), ("no", "account status is hold"))
        self.assertEqual(self.rows["A006"]["why_not"], "relationship is customer")
        self.assertEqual(self.rows["A008"]["why_not"], "account status is live_deal")
        self.assertEqual(self.rows["A011"]["why_not"], "only context signals (weight 0)")
        self.assertTrue(self.rows["A011"]["why_now"].startswith("weak case"))

    def test_competitor_without_signals_not_listed(self):
        self.assertNotIn("A010", self.rows)

    def test_order_playable_then_score_then_id(self):
        order = [r["account_id"] for r in self.result["scored"]]
        self.assertEqual(order[:5], ["A001", "A003", "A009", "A002", "A007"])
        self.assertTrue(all(r["playable"] == "no" for r in self.result["scored"][5:]))

    def test_intent_never_cited(self):
        for r in self.result["scored"]:
            self.assertNotIn("research surge", r["why_now"].lower())
        self.assertTrue(self.rows["A004"]["why_now"].startswith("Timing only"))
        self.assertEqual(self.rows["A004"]["source_url"], "")
        self.assertEqual(self.rows["A009"]["top_type"], "funding")  # citable beats higher-value intent

    def test_intent_only_account_is_held(self):
        # D2 (Oct 22): a message needs a fact it can quote; intent is timing only.
        self.assertEqual((self.rows["A004"]["playable"], self.rows["A004"]["why_not"]),
                         ("no", "intent only: find a citable reason first"))

    def test_fit_by_timing_quadrant(self):
        got = {aid: self.rows[aid]["quadrant"] for aid in ("A001", "A004", "A011")}
        self.assertEqual(got, {"A001": "act", "A004": "nurture", "A011": "nurture"})
        self.assertIn("Fit by timing", (self.ws / "signals/report.md").read_text())

    def test_why_now_is_source_summary_with_date(self):
        self.assertEqual(self.rows["A002"]["why_now"],
                         "Posted an opening for an Accounts Payable Manager (source dated 2026-10-05).")

    def test_seats(self):
        self.assertEqual(self.rows["A001"]["seat"], "Dana Whitfield, Chief Financial Officer (the named new leader)")
        self.assertIn("not Marcus Lee", self.rows["A003"]["seat"])

    def test_raw_untouched_and_outputs_written(self):
        self.assertEqual(digest(self.ws / "signals" / "raw"), self.raw_before)
        for name in ("scored.csv", "signals.csv", "report.md"):
            self.assertTrue((self.ws / "signals" / name).is_file(), name)
        report = (self.ws / "signals" / "report.md").read_text()
        self.assertIn("Nothing was sent", report)
        self.assertIn("Open each source link", report)


class Rules(unittest.TestCase):
    def make_ws(self, rows, accounts=None, config=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name) / "gtm"
        (ws / "input").mkdir(parents=True)
        (ws / "signals" / "raw" / "2026-10-15").mkdir(parents=True)
        (ws / "input" / "accounts.csv").write_text(accounts or (
            "account_id,name,domain,other_domains,employees,industry,country,tier,relationship,status,owner,crm_id,notes\n"
            "A1,Alpha Works,alpha.example,,500,software,US,,,active,,,\n"
            "A2,Alpha Works LLC,alpha-two.example,,500,software,US,,,active,,,\n"))
        (ws / "signals" / "raw" / "2026-10-15" / "s.csv").write_text(HEADER + rows)
        if config is not None:
            (ws / "gtm.json").write_text(json.dumps(config))
        return ws

    def test_ambiguous_name_is_not_matched(self):
        ws = self.make_ws("X1,Alpha Works Inc,,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n")
        result = ss.score(ws, TODAY)
        t = result["trace"][0]
        self.assertEqual((t["status"], t["reason"]), ("unmatched", "name matches more than one account"))

    def test_future_and_undated_rows_skipped(self):
        ws = self.make_ws("X1,,alpha.example,hiring,2026-11-01,Later,https://jobs.example/x1,,\n"
                          "X2,,alpha.example,hiring,,No date,https://jobs.example/x2,,\n")
        statuses = [(t["status"], t["reason"]) for t in ss.score(ws, TODAY)["trace"]]
        self.assertEqual(statuses[0], ("skipped", "event date is after today"))
        self.assertEqual(statuses[1][0], "skipped")

    def test_config_weight_changes_score(self):
        rows = "X1,,alpha.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n"
        base = ss.score(self.make_ws(rows), TODAY)["scored"][0]["score"]
        tuned = ss.score(self.make_ws(rows, config={"signals": {"types": {"hiring": {"weight": 2}}}}),
                         TODAY)["scored"][0]["score"]
        self.assertEqual((base, tuned), (4.0, 2.0))

    def test_bad_config_rejected(self):
        ws = self.make_ws("", config={"signals": {"recency": [[90, 1.0], [30, 0.5]]}})
        with self.assertRaises(ss.ConfigError):
            ss.score(ws, TODAY)

    def test_refuses_to_write_into_raw(self):
        ws = self.make_ws("")
        with self.assertRaisesRegex(ValueError, "signals/raw"):
            ss.score(ws, TODAY, out_dir=ws / "signals" / "raw" / "2026-10-15")

    def test_two_posts_same_type_do_not_double_count(self):
        ws = self.make_ws("X1,,alpha.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n"
                          "X2,,alpha.example,hiring,2026-10-11,Hiring an AP lead,https://jobs.example/x2,,\n")
        row = ss.score(ws, TODAY)["scored"][0]
        self.assertEqual((row["score"], row["live_signals"]), (4.0, 2))
        self.assertIn("AP lead", row["why_now"])  # tie on value goes to the newer event

    def test_cli_requires_today(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            ss.main(["--workspace", str(EXAMPLE)])

    def add_pull(self, ws, day, rows):
        folder = ws / "signals" / "raw" / day
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "s.csv").write_text(HEADER + rows)

    def test_skipped_row_then_corrected_pull_scores(self):
        ws = self.make_ws("S018,,alpha.example,growth,2026-10-01,Opened a new site,,,\n")
        self.add_pull(ws, "2026-10-16", "S018,,alpha.example,growth,2026-10-01,Opened a new site,"
                                        "https://news.example/s018,,\n")
        result = ss.score(ws, TODAY)
        statuses = [(t["raw_file"].split("/")[2], t["status"]) for t in result["trace"]]
        self.assertEqual(statuses, [("2026-10-15", "duplicate"), ("2026-10-16", "live")])
        self.assertIn("replaced by the newer pull 2026-10-16 (was skipped", result["trace"][0]["reason"])
        self.assertEqual(result["scored"][0]["source_url"], "https://news.example/s018")
        report = (ws / "signals" / "report.md").read_text()
        not_used = report.split("## Not used")[1].split("##")[0]
        self.assertNotIn("S018", not_used)   # a corrected row is not a problem to fix

    def test_newer_pull_replaces_older_copy(self):
        ws = self.make_ws("X1,,alpha.example,hiring,2026-10-10,Hiring a controler,https://jobs.example/x1,,\n")
        self.add_pull(ws, "2026-10-16", "X1,,alpha.example,hiring,2026-10-10,Hiring a controller,"
                                        "https://jobs.example/x1,,\n")
        result = ss.score(ws, TODAY)
        old, new = result["trace"]
        self.assertEqual((old["status"], old["reason"]), ("duplicate", "replaced by the newer pull 2026-10-16"))
        self.assertEqual(new["status"], "live")
        self.assertIn("Hiring a controller (", result["scored"][0]["why_now"])
        self.assertEqual(result["counts"]["duplicate"], 1)

    def test_skipped_correction_does_not_replace_good_row(self):
        ws = self.make_ws("X1,,alpha.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n")
        self.add_pull(ws, "2026-10-16", "X1,,alpha.example,hiring,2026-10-10,Hiring a controller,,,\n")
        statuses = [t["status"] for t in ss.score(ws, TODAY)["trace"]]
        self.assertEqual(statuses, ["live", "skipped"])

    def test_domain_match_with_other_name_gets_check_note(self):
        ws = self.make_ws("X1,Alpha Foods,alpha.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n"
                          "X2,Alpha Works Inc,alpha.example,growth,2026-10-09,New site,https://news.example/x2,,\n")
        result = ss.score(ws, TODAY)
        x1, x2 = result["trace"]
        self.assertEqual(x1["status"], "live")
        self.assertIn("source names Alpha Foods; your account is Alpha Works", x1["check"])
        self.assertEqual(x2["check"], "")  # same name after legal endings are removed
        self.assertIn("Alpha Foods", result["scored"][0]["check"])
        report = (ws / "signals" / "report.md").read_text()
        self.assertIn("## Check before use (1)", report)

    def test_relationships_follow_icp_and_parent_decides_always_blocked(self):
        accounts = ("account_id,name,domain,other_domains,employees,industry,country,tier,relationship,status,owner,crm_id,notes\n"
                    "A1,Alpha Works,alpha.example,,500,software,US,,partner,active,,,\n"
                    "A2,Beta Works,beta.example,,500,software,US,,parent_decides,active,,,\n")
        rows = ("X1,,alpha.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n"
                "X2,,beta.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x2,,\n")
        cfg = {"icp": {"exclude_relationships": ["competitor"]}}
        rows_by_id = {r["account_id"]: r for r in ss.score(self.make_ws(rows, accounts, cfg), TODAY)["scored"]}
        self.assertEqual(rows_by_id["A1"]["playable"], "yes")  # partner is not excluded by this ICP
        self.assertEqual(rows_by_id["A2"]["playable"], "no")
        self.assertIn("parent_decides", rows_by_id["A2"]["why_not"])

    def test_byte_order_mark_csv_reads(self):
        ws = self.make_ws("X1,,alpha.example,hiring,2026-10-10,Hiring a controller,https://jobs.example/x1,,\n")
        path = ws / "input" / "accounts.csv"
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        raw = ws / "signals" / "raw" / "2026-10-15" / "s.csv"
        raw.write_bytes(b"\xef\xbb\xbf" + raw.read_bytes())
        self.assertEqual(ss.score(ws, TODAY)["scored"][0]["account_id"], "A1")


if __name__ == "__main__":
    unittest.main()
