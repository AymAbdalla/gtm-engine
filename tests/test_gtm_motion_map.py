"""Rules for aym-gtm motion-map: graph checks, ownership rules, the automation pick and the diagram."""
import copy
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/motion-map"
spec = importlib.util.spec_from_file_location("check_map", SKILL / "scripts/check_map.py")
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)

EXAMPLE = SKILL / "assets/example"
CFG = cm.load_config(None)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cm.main(argv)
    return code, out.getvalue() + err.getvalue()


def stage(sid, nxt=(), **kw):
    s = {"id": sid, "name": sid, "kind": "task", "trigger": {"type": "event", "detail": ""}, "work": "mechanical",
         "owner": "rep", "raci": {"r": "rep", "a": "rep", "c": [], "i": []}, "systems": [], "writes": [],
         "automation": {"tier": "manual", "level": "none"},
         "readiness": {"visible_today": ["the CRM fields for this step"], "missing": [], "cleanup": []},
         "next": [{"to": t, "when": w} for t, w in nxt], "risk": {"automated_wrong": "low", "left_manual": "low"}}
    s.update(kw)
    return s


def base_map(stages, start=None, ends=None):
    return {"motion": {"name": "t"},
            "roles": [{"id": "rep", "kind": "human"}, {"id": "builder", "kind": "scheduled_builder"},
                      {"id": "executor", "kind": "executor"}],
            "systems": [{"id": "files", "live": False, "operator": "builder"},
                        {"id": "crm", "live": True, "operator": "executor"},
                        {"id": "seq", "live": True, "operator": "rep"}],
            "start": start or stages[0]["id"], "ends": ends if ends is not None else [stages[-1]["id"]], "stages": stages}


def codes(res):
    return [c for c, _, _ in res.findings]


class ExampleTests(unittest.TestCase):
    def test_clean_example_matches_committed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run(["--workspace", str(EXAMPLE), "--out", tmp])
            self.assertEqual(code, 0, text)
            self.assertIn("Automate first: S12", text)
            for name in ("map.md", "checks.md"):
                self.assertEqual(Path(tmp, name).read_text(), (EXAMPLE / "motion" / name).read_text(), name)

    def test_broken_example_reports_the_two_mistakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["--workspace", str(EXAMPLE / "broken"), "--out", tmp])
            self.assertEqual(code, 1)
            checks = Path(tmp, "checks.md").read_text()
            self.assertEqual(checks, (EXAMPLE / "broken/motion/checks.md").read_text())
        m = cm.load_map(EXAMPLE / "broken/motion/map.json")
        res = cm.analyze(m, CFG)
        self.assertIn(("G1", "S12", "edge points to stage 'S99', which does not exist"), res.findings)
        self.assertEqual([w for c, w, _ in res.findings if c == "G3"], ["S08", "S08"])
        self.assertEqual(res.unresolved, [("S12", "edge to missing stage 'S99'")])

    def test_broken_example_leaves_flagged_stages_out_of_the_pick(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run(["--workspace", str(EXAMPLE / "broken"), "--out", tmp])
            self.assertIn("Automate first (provisional: fix the flow first): S04", text)
            md = Path(tmp, "map.md").read_text()
            self.assertEqual(md, (EXAMPLE / "broken/motion/map.md").read_text())
        self.assertIn("- S12 Log outcomes and set the next step: has findings (G1, G2, G4)", md)
        self.assertIn("- S13 Sync the CRM: has findings (G4)", md)

    def test_broken_example_config_is_the_canonical_one(self):
        canon = (ROOT / "plugins/aym-gtm/skills/icp-define/assets/example/gtm.json").read_text()
        self.assertEqual((EXAMPLE / "broken/gtm.json").read_text(), canon)

    def test_example_configs_match_the_canonical_one_plus_motion(self):
        canon = json.loads((ROOT / "plugins/aym-gtm/skills/icp-define/assets/example/gtm.json").read_text())
        mine = json.loads((EXAMPLE / "gtm.json").read_text())
        self.assertIn("motion", mine)
        self.assertEqual({k: v for k, v in mine.items() if k != "motion"},
                         {k: v for k, v in canon.items() if k != "motion"})


class GraphTests(unittest.TestCase):
    def test_no_way_in_no_way_out_and_cut_off(self):
        m = base_map([stage("A", [("B", "")]), stage("B"), stage("C", [("B", "")]), stage("D")], ends=["B"])
        res = cm.analyze(m, CFG)
        msgs = [(c, w) for c, w, _ in res.findings]
        self.assertIn(("G2", "C"), msgs)            # nothing leads to C
        self.assertIn(("G2", "D"), msgs)            # D has no way in and no way out
        self.assertIn(("G4", "C, D"), msgs)
        self.assertNotIn(("G2", "B"), msgs)         # B is an end

    def test_decision_needs_two_conditioned_branches_and_else(self):
        d = stage("D", [("E", "yes"), ("F", "")], kind="decision",
                  decision={"question": "q", "owner": "rule", "exact_fact": True, "consequential": False,
                            "if_wrong": "x", "check": "y", "accountable": "rep"})
        m = base_map([stage("A", [("D", "")]), d, stage("E"), stage("F")], ends=["E", "F"])
        found = [msg for c, w, msg in cm.analyze(m, CFG).findings if c == "G3"]
        self.assertTrue(any("no condition" in f for f in found))
        self.assertTrue(any("anything else" in f for f in found))
        d["next"] = [{"to": "E", "when": "yes"}, {"to": "F", "when": "else"}]
        self.assertEqual([c for c in codes(cm.analyze(m, CFG)) if c == "G3"], [])

    def test_unresolved_references_are_listed(self):
        m = base_map([stage("A", [("Z", "")], owner="ghost", writes=["nowhere"])], ends=["A"])
        res = cm.analyze(m, CFG)
        refs = [msg for _, msg in res.unresolved]
        self.assertIn("edge to missing stage 'Z'", refs)
        self.assertIn("owner 'ghost' is not a role", refs)
        self.assertIn("system 'nowhere' is not defined", refs)


class RuleTests(unittest.TestCase):
    def one(self, **kw):
        return cm.analyze(base_map([stage("A", **kw)], ends=["A"]), CFG)

    def test_one_operator_per_system(self):
        res = self.one(writes=["crm"])
        self.assertIn(("R1", "A", "rep writes to crm, but its one operator is executor"), res.findings)

    def test_irreversible_needs_a_person(self):
        res = self.one(irreversible=True, writes=["seq"], automation={"tier": "automatic", "level": "draft"},
                       loop={"repeats_weekly": True, "auto_check": "x", "budget": "y", "sees_results": True,
                             "state_file": "s", "do_not_retry": [], "stop_after_identical_runs": 2})
        msgs = [msg for c, _, msg in res.findings if c == "R2"]
        self.assertTrue(any("runs automatically" in m for m in msgs))
        self.assertTrue(any("no human approval point" in m for m in msgs))

    def test_builder_never_writes_a_live_tool_and_executor_never_judges(self):
        res = self.one(owner="builder", raci={"r": "builder", "a": "rep"}, writes=["crm"])
        self.assertIn("R3", codes(res))
        res = self.one(owner="executor", raci={"r": "executor", "a": "rep"}, work="judgment")
        self.assertIn("R4", codes(res))

    def test_not_ready_cannot_be_automated(self):
        res = self.one(automation={"tier": "batch", "level": "suggest"},
                       readiness={"visible_today": ["a list"], "missing": ["no ids"], "cleanup": []})
        self.assertIn(("R5", "A", "automated while not ready: no ids"), res.findings)

    def test_model_never_owns_a_consequential_gate(self):
        d = stage("D", [("E", "yes"), ("E2", "else")], kind="decision",
                  decision={"question": "q", "owner": "model", "exact_fact": True, "consequential": True,
                            "if_wrong": "x", "check": "y", "accountable": "rep"})
        res = cm.analyze(base_map([d, stage("E"), stage("E2")], ends=["E", "E2"]), CFG)
        self.assertEqual([c for c in codes(res) if c == "R6"], ["R6", "R6"])

    def test_loop_check(self):
        res = self.one(automation={"tier": "automatic", "level": "draft"})
        self.assertIn(("A", "runs automatically but has no loop check"), res.unchecked)
        res = self.one(automation={"tier": "automatic", "level": "draft"},
                       loop={"repeats_weekly": True, "auto_check": "", "budget": "y", "sees_results": True,
                             "state_file": "s", "do_not_retry": [], "stop_after_identical_runs": 9})
        msgs = [msg for c, _, msg in res.findings if c == "R7"]
        self.assertTrue(any("no automatic check" in m for m in msgs))
        self.assertTrue(any("at most 3 runs" in m for m in msgs))

    def test_missing_card_answers_are_unchecked_not_clean(self):
        s = stage("A")
        del s["trigger"], s["work"], s["readiness"]
        res = cm.analyze(base_map([s], ends=["A"]), CFG)
        self.assertEqual(res.findings, [])
        self.assertFalse(res.clean)
        self.assertEqual(len(res.unchecked), 3)


class PickTests(unittest.TestCase):
    def test_pick_order_and_exclusions(self):
        stages = [
            stage("A", [("B", "")], volume_per_week=100, minutes_per_item=5, cold_rate=0.1),
            stage("B", [("C", "")], volume_per_week=10, minutes_per_item=1, cold_rate=0.4),
            stage("C", [("D", "")], volume_per_week=500, minutes_per_item=5, cold_rate=0.9,
                  risk={"automated_wrong": "high", "left_manual": "high"}),
            stage("D", [("E", "")], volume_per_week=500, minutes_per_item=5, irreversible=True),
            stage("E", [("F", "")], volume_per_week=500, minutes_per_item=5, work="judgment"),
            stage("F", [("G", "")], volume_per_week=9, minutes_per_item=9, cold_rate=0.4,
                  readiness={"visible_today": ["a list"], "missing": ["no ids"], "cleanup": ["fix ids"]}),
            stage("G", volume_per_week=1000, minutes_per_item=1, cold_rate=0.1,
                  risk={"automated_wrong": "medium", "left_manual": "high"}),
        ]
        ready, not_ready = cm.pick_automation(base_map(stages), CFG)
        self.assertEqual([x["id"] for x in ready], ["B", "A", "G"])  # low risk first, then cold rate, then minutes
        self.assertEqual([x["id"] for x in not_ready], ["F"])
        self.assertEqual(not_ready[0]["cleanup"], ["fix ids"])
        self.assertEqual(cm.next_level("none"), "observe")
        self.assertEqual(cm.next_level("draft"), "draft")

    def test_stage_with_findings_is_never_picked(self):
        # B is the best candidate on every measure but has an edge to a missing stage.
        stages = [stage("A", [("B", "")], volume_per_week=10, minutes_per_item=1, cold_rate=0.1),
                  stage("B", [("C", ""), ("ZZ", "")], volume_per_week=900, minutes_per_item=9, cold_rate=0.9),
                  stage("C")]
        m = base_map(stages)
        ready, not_ready, unknown, left_out = cm.pick_report(m, CFG)
        self.assertEqual([x["id"] for x in ready], ["A", "C"])
        self.assertEqual([(x["id"], x["why"].split(";")[0]) for x in left_out], [("B", "has findings (G1)")])
        self.assertEqual(cm.pick_automation(m, CFG)[0][0]["id"], "A")

    def test_cut_off_stages_are_all_left_out(self):
        stages = [stage("A", [("B", "")]), stage("B"), stage("C", [("D", "")]), stage("D")]
        _, _, _, left_out = cm.pick_report(base_map(stages, ends=["B", "D"]), CFG)
        self.assertEqual([x["id"] for x in left_out], ["C", "D"])

    def test_top_level_stage_is_never_picked(self):
        stages = [stage("A", [("B", "")], automation={"tier": "batch", "level": "draft"}, cold_rate=0.9),
                  stage("B", automation={"tier": "manual", "level": "suggest"})]
        ready, _, _, left_out = cm.pick_report(base_map(stages), CFG)
        self.assertEqual([x["id"] for x in ready], ["B"])
        self.assertEqual(left_out[0]["id"], "A")
        self.assertIn("already at the top automation level (draft)", left_out[0]["why"])
        md = cm.render_map(base_map(stages), CFG, cm.analyze(base_map(stages), CFG))
        self.assertIn("move from level suggest to draft", md)
        self.assertNotIn("move from level draft to draft", md)
        self.assertIn("- A A: already at the top automation level (draft)", md)

    def test_unknown_readiness_is_never_ready(self):
        no_block = stage("A", [("B", "")], cold_rate=0.9)
        del no_block["readiness"]
        no_missing = stage("B", [("C", "")], readiness={"visible_today": ["a list"]}, cold_rate=0.8)
        known = stage("C", cold_rate=0.1)
        m = base_map([no_block, no_missing, known])
        res = cm.analyze(m, CFG)
        self.assertIn(("B", "readiness unknown: no missing list (write [] when nothing is missing)"), res.unchecked)
        ready, not_ready, unknown, left_out = cm.pick_report(m, CFG, res)
        self.assertEqual([x["id"] for x in ready], ["C"])
        self.assertEqual([x["id"] for x in unknown], ["A", "B"])
        self.assertEqual(not_ready, [])
        md = cm.render_map(m, CFG, res)
        self.assertIn("Readiness unknown (these can't be picked", md)
        for q in cm.READINESS_QUESTIONS:
            self.assertIn(q, md)
        self.assertIn("| B | a list | unknown | - |", md)

    def test_all_empty_readiness_block_is_unknown(self):
        empty = stage("A", [("B", "")], readiness={"visible_today": [], "missing": [], "cleanup": []}, cold_rate=0.9)
        known = stage("B", cold_rate=0.1)
        m = base_map([empty, known])
        res = cm.analyze(m, CFG)
        self.assertIn(("A", "readiness unknown: visible_today is empty (say what can be seen today)"), res.unchecked)
        ready, not_ready, unknown, left_out = cm.pick_report(m, CFG, res)
        self.assertEqual([x["id"] for x in ready], ["B"])
        self.assertEqual([x["id"] for x in unknown], ["A"])
        nothing = base_map([stage("A", readiness={})], ends=["A"])
        ready, _, unknown, _ = cm.pick_report(nothing, CFG)
        self.assertEqual((ready, [x["id"] for x in unknown]), ([], ["A"]))
        code_out = cm.render_map(nothing, CFG, cm.analyze(nothing, CFG))
        self.assertIn("No step is ready to automate", code_out)


class DiagramAndCliTests(unittest.TestCase):
    def test_large_map_is_capped_with_a_note(self):
        stages = [stage(f"S{i:02d}", [(f"S{i + 1:02d}", "")]) for i in range(1, 20)] + [stage("S20")]
        flow, note = cm.mermaid(base_map(stages), dict(CFG, max_nodes=15))
        self.assertEqual(sum(1 for line in flow.splitlines() if line.strip().endswith('"]')), 15)
        self.assertIn("Showing 15 of 20", note)

    def test_decision_drawn_as_diamond_and_quotes_escaped(self):
        d = stage("D", [("E", 'say "yes"'), ("E", "else")], kind="decision", name='Ready?')
        flow, _ = cm.mermaid(base_map([d, stage("E")]), CFG)
        self.assertIn('D{"D Ready?"}', flow)
        self.assertIn("-->|say 'yes'| E", flow)

    def test_input_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run(["--workspace", tmp])
            self.assertEqual(code, 2)
            self.assertIn("no map", text)
            mp = Path(tmp, "motion")
            mp.mkdir()
            (mp / "map.md").write_text(json.dumps(base_map([stage("A")])))
            code, text = run(["--workspace", tmp, "--map", str(mp / "map.md")])
            self.assertEqual(code, 2)
            self.assertIn("refusing to write over the input map", text)
            Path(tmp, "gtm.json").write_text(json.dumps({"motion": {"max_nodes": 1}}))
            (mp / "map.json").write_text(json.dumps(base_map([stage("A")])))
            code, text = run(["--workspace", tmp])
            self.assertEqual(code, 2)
            self.assertIn("max_nodes", text)

    def test_reads_files_with_a_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp = Path(tmp, "motion")
            mp.mkdir()
            (mp / "map.json").write_text(json.dumps(base_map([stage("A")])), encoding="utf-8-sig")
            code, _ = run(["--workspace", tmp])
            self.assertEqual(code, 0)


class HonestPickTests(unittest.TestCase):
    """Oct 22 review: a pick on a broken map, and a send step relabeled as reversible."""

    def test_broken_flow_makes_the_pick_provisional(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run(["--workspace", str(EXAMPLE / "broken"), "--out", tmp])
            self.assertEqual(code, 1)
            self.assertIn("provisional", text.lower())
            self.assertIn("Provisional", Path(tmp, "map.md").read_text())
            code, text = run(["--workspace", str(EXAMPLE), "--out", tmp])
            self.assertNotIn("provisional", text.lower())

    def test_writing_to_a_send_tool_counts_as_irreversible(self):
        m = json.loads((EXAMPLE / "motion/map.json").read_text())
        for s in m["stages"]:
            if s["id"] == "S07":
                s["irreversible"] = False
        res = cm.analyze(m, CFG)
        self.assertIn(("R2", "S07"), [(c, w) for c, w, _ in res.findings])
        for s in m["stages"]:
            if s["id"] == "S07":
                s["irreversible_override"] = "the sequencer here only stages drafts; a person sends"
        res = cm.analyze(m, CFG)
        self.assertNotIn(("R2", "S07"), [(c, w) for c, w, _ in res.findings])

    def test_measured_volume_from_the_activity_log(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            shutil.copytree(EXAMPLE, ws)
            m = json.loads((ws / "motion/map.json").read_text())
            for s in m["stages"]:
                if s["id"] == "S12":
                    s["measure"] = {"channel": "call", "direction": "out"}
            (ws / "motion/map.json").write_text(json.dumps(m))
            rows = ["activity_id,timestamp,person_id,account_id,channel,direction,outcome"]
            for i in range(40):
                rows.append(f"a{i},2026-10-{(i % 20) + 1:02d}T10:00:00-04:00,p{i},A1,call,out,no_answer")
            rows.append("x1,2026-08-01T10:00:00-04:00,p1,A1,call,out,no_answer")   # older than 4 weeks
            (ws / "log").mkdir()
            (ws / "log/activity.csv").write_text("\n".join(rows) + "\n")
            code, text = run(["--workspace", str(ws), "--out", str(ws / "out"), "--today", "2026-10-22"])
            md = (ws / "out/map.md").read_text()
        self.assertIn("about 10 items a week (measured from the log)", md)


if __name__ == "__main__":
    unittest.main()
