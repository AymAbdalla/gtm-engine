"""Rules for aym-gtm icp-define: config checks, ICP sorting and market estimates."""
import copy
import csv
import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/icp-define"
spec = importlib.util.spec_from_file_location("icp_check", SKILL / "scripts/icp_check.py")
icp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icp)

EXAMPLE = SKILL / "assets/example"
CFG = json.loads((EXAMPLE / "gtm.json").read_text())


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = icp.main(argv)
    return code, out.getvalue() + err.getvalue()


def account(**kw):
    row = {"account_id": "t-1", "name": "Test Co", "employees": "500", "industry": "logistics",
           "country": "US", "tier": "", "relationship": "", "status": "active"}
    row.update(kw)
    return row


class ConfigTests(unittest.TestCase):
    def test_example_config_is_clean(self):
        errors, warnings = icp.validate_config(CFG)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_example_has_every_shared_section(self):
        for key in ("seller", "icp", "personas", "not_buyer_titles", "review_titles", "region_title_rule",
                    "segments", "market_bands", "scoring", "send_gate", "signals", "copy"):
            self.assertIn(key, CFG, key)

    def test_size_band_out_of_order(self):
        cfg = copy.deepcopy(CFG)
        cfg["icp"]["size"]["sweet_min"] = 1500  # above sweet_max
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("ordered" in e for e in errors))

    def test_bad_regex_and_duplicate_persona(self):
        cfg = copy.deepcopy(CFG)
        cfg["personas"][0]["title_patterns"].append("(unclosed")
        cfg["personas"].append(dict(cfg["personas"][1]))
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("does not compile" in e for e in errors))
        self.assertTrue(any("used twice" in e for e in errors))

    def test_count_without_source_is_rejected(self):
        cfg = copy.deepcopy(CFG)
        cfg["segments"][0]["market_count_source"] = ""
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("market_count_source" in e for e in errors))

    def test_industry_in_and_out_conflict(self):
        cfg = copy.deepcopy(CFG)
        cfg["icp"]["industries_out"].append("logistics")
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("both in and out" in e for e in errors))

    def test_recency_must_go_up(self):
        cfg = copy.deepcopy(CFG)
        cfg["signals"]["recency"] = [[90, 0.7], [30, 1.0]]
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("recency" in e for e in errors))

    def test_contact_blocks_use_one_key_each(self):
        cfg = copy.deepcopy(CFG)
        cfg["send_gate"]["block_person_status"] = ["do_not_contact"]
        cfg["stop_statuses"] = ["hold", "sleeping"]
        cfg["channel_block_tags"] = {"fax": ["x"]}
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("block_person_status moved" in e for e in errors))
        self.assertTrue(any("unknown values: sleeping" in e for e in errors))
        self.assertTrue(any("must include do_not_contact" in e for e in errors))
        self.assertTrue(any("channel_block_tags" in e for e in errors))

    def test_tag_cannot_be_opt_out_and_left(self):
        cfg = copy.deepcopy(CFG)
        cfg["left_tags"] = ["moved", "opted_out"]
        errors, _ = icp.validate_config(cfg)
        self.assertTrue(any("both an opt-out and a left tag: opted_out" in e for e in errors))

    def test_missing_optional_sections_only_warn(self):
        cfg = {k: CFG[k] for k in ("icp", "personas")}
        errors, warnings = icp.validate_config(cfg)
        self.assertEqual(errors, [])
        self.assertTrue(any("send_gate" in w for w in warnings))

    def test_config_error_stops_before_sorting(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy.deepcopy(CFG)
            del bad["personas"]
            Path(tmp, "gtm.json").write_text(json.dumps(bad))
            code, text = run(["--workspace", tmp])
            self.assertEqual(code, 1)
            self.assertIn("personas", text)


class SortTests(unittest.TestCase):
    def test_reason_order_relationship_first(self):
        r = icp.classify_account(account(relationship="competitor", country="DE", industry="government"), CFG)
        self.assertEqual(r["in_icp"], "no")
        self.assertIn("competitor", r["icp_reason"])

    def test_unknown_headcount_is_not_out(self):
        r = icp.classify_account(account(employees=""), CFG)
        self.assertEqual(r["in_icp"], "unknown")

    def test_band_edges(self):
        self.assertEqual(icp.classify_account(account(employees="200"), CFG)["size_band"], "in_band")
        self.assertEqual(icp.classify_account(account(employees="300"), CFG)["size_band"], "sweet_spot")
        self.assertEqual(icp.classify_account(account(employees="199"), CFG)["in_icp"], "no")
        self.assertEqual(icp.classify_account(account(employees="2,001"), CFG)["in_icp"], "no")

    def test_status_does_not_change_fit(self):
        r = icp.classify_account(account(status="hold"), CFG)
        self.assertEqual(r["in_icp"], "yes")

    def test_segment_and_points(self):
        r = icp.classify_account(account(employees="640", tier="P1"), CFG)
        self.assertEqual(r["segment"], "mid-logistics")
        self.assertEqual(r["account_points"], 3 + 1 + 3)
        self.assertEqual(r["points_detail"], "sweet_spot 3; segment_match 1; tier P1 3")
        r = icp.classify_account(account(employees="1500"), CFG)  # logistics but above segment range
        self.assertEqual(r["segment"], "unsegmented")
        self.assertEqual(r["account_points"], 1)

    def test_example_list_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run(["--workspace", str(EXAMPLE), "--out", tmp])
            self.assertEqual(code, 0, text)
            self.assertIn("in 6, out 8, unknown 1", text)
            with open(Path(tmp, "accounts-icp.csv"), newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 15)
            self.assertIn("notes", rows[0])  # input columns are kept
            report = Path(tmp, "icp-check.md").read_text()
            self.assertIn("estimate, not forecast", report)

    def test_refuses_to_overwrite_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "input").mkdir()
            (ws / "gtm.json").write_text(json.dumps(CFG))
            src = (EXAMPLE / "input/accounts.csv").read_text()
            target = ws / "accounts-icp.csv"
            target.write_text(src)
            code, text = run(["--workspace", tmp, "--accounts", str(target), "--out", tmp])
            self.assertEqual(code, 2)
            self.assertIn("Refusing", text)
            self.assertEqual(target.read_text(), src)


class MarketTests(unittest.TestCase):
    def test_noise_adjustment_and_band(self):
        rows = {r["segment"]: r for r in icp.market_estimates(CFG, {})}
        self.assertEqual(rows["mid-logistics"]["estimate"], 3700)  # 4200 * (1 - 3/25) = 3696
        self.assertEqual(rows["mid-logistics"]["band"], "sweet spot")
        self.assertEqual(rows["manufacturing"]["band"], "too broad")
        self.assertEqual(rows["software"]["band"], "too narrow")
        self.assertIsNone(rows["services-health"]["estimate"])

    def test_two_significant_figures(self):
        self.assertEqual(icp.two_sig(3696), 3700)
        self.assertEqual(icp.two_sig(61234), 61000)
        self.assertEqual(icp.two_sig(0), 0)

    def test_sam_only_with_value_and_share(self):
        cfg = copy.deepcopy(CFG)
        self.assertTrue(all(r["sam"] is None for r in icp.market_estimates(cfg, {})))
        cfg["seller"]["average_contract_value"] = 20000
        cfg["segments"][0]["addressable_share"] = 0.1
        sam = icp.market_estimates(cfg, {})[0]["sam"]
        self.assertEqual(sam, icp.two_sig(4200 * (1 - 3 / 25) * 0.1 * 20000))


class WonDealsAndReviewTests(unittest.TestCase):
    """Oct 22 review: check the ICP against won deals, and flag a stale ICP."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / "input").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_cfg(self, **icp_extra):
        cfg = copy.deepcopy(CFG)
        cfg["icp"].update(icp_extra)
        (self.ws / "gtm.json").write_text(json.dumps(cfg))

    def test_share_of_won_deals_inside_the_icp(self):
        self.write_cfg()
        cols = ["account_id", "name", "employees", "industry", "country", "relationship"]
        inside = [{"account_id": f"W{i}", "name": f"Won {i}", "employees": "500", "industry": "logistics",
                   "country": "US", "relationship": "customer"} for i in range(7)]
        outside = [{"account_id": "W7", "name": "Tiny Won", "employees": "40", "industry": "logistics", "country": "US"},
                   {"account_id": "W8", "name": "Retail Won", "employees": "500", "industry": "retail", "country": "US"},
                   {"account_id": "W9", "name": "German Won", "employees": "500", "industry": "logistics", "country": "DE"}]
        with (self.ws / "input/won-deals.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in inside + outside:
                w.writerow({c: r.get(c, "") for c in cols})
        code, out = run(["--workspace", str(self.ws), "--out", str(self.ws / "icp"), "--today", "2026-10-22"])
        self.assertEqual(code, 0, out)
        self.assertIn("7 of 10 won deals inside the ICP", out)
        report = (self.ws / "icp/icp-check.md").read_text()
        for name in ("Tiny Won", "Retail Won", "German Won"):
            self.assertIn(name, report)

    def test_won_deals_with_only_account_id_are_looked_up(self):
        # Oct 22 check finding: the docs promise this, but the file was rejected.
        self.write_cfg()
        cols = ["account_id", "name", "employees", "industry", "country"]
        with (self.ws / "input/accounts.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerow({"account_id": "W1", "name": "Good Won", "employees": "500", "industry": "logistics", "country": "US"})
            w.writerow({"account_id": "W2", "name": "Retail Won", "employees": "500", "industry": "retail", "country": "US"})
        (self.ws / "input/won-deals.csv").write_text("account_id\nW1\nW2\nW9\n")
        code, out = run(["--workspace", str(self.ws), "--out", str(self.ws / "icp"), "--today", "2026-10-22"])
        self.assertEqual(code, 0, out)
        self.assertIn("1 of 3 won deals inside the ICP", out)
        report = (self.ws / "icp/icp-check.md").read_text()
        self.assertIn("Retail Won", report)
        self.assertIn("1 unknown", out)
        self.assertIn("W9", report)

    def test_past_review_date_warns(self):
        self.write_cfg(review_by="2026-09-30")
        code, out = run(["--workspace", str(self.ws), "--today", "2026-10-22"])
        self.assertEqual(code, 0, out)
        self.assertIn("review the ICP", out)

    def test_config_reference_documents_every_section(self):
        doc = (SKILL / "references/config.md").read_text()
        missing = [key for key in CFG if f"`{key}`" not in doc]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
