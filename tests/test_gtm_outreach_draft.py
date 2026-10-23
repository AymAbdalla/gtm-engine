"""Rules of the aym-gtm outreach-draft copy checker, tested on made-up drafts."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/aym-gtm/skills/outreach-draft"
EXAMPLE = SKILL / "assets/example"
spec = importlib.util.spec_from_file_location("lint_copy", SKILL / "scripts/lint_copy.py")
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)

REGISTRY = lint.load_registry(json.loads((EXAMPLE / "outreach/proof.json").read_text()))
RULES = lint.copy_rules(json.loads((EXAMPLE / "gtm.json").read_text()))
TODAY = lint.parse_date("2026-11-02")

GOOD_BODY = ("Hi Dana, I saw Brightmill posted an opening for an AP lead on October 20. When a finance team "
             "adds people, month end often gets slower before it gets faster. Finance teams on Ledgerline "
             "close the month 3 days sooner. Is close speed something you are working on this quarter?")


def draft(body=GOOD_BODY, subject="Brightmill month end", sent=" ", **fields):
    base = {"person_id": "p-014", "persona": "controller", "channel": "email", "thread": "new",
            "angle": "trigger", "proof": "pr-01",
            "why_now": "Brightmill posted an AP lead opening on 2026-10-20.",
            "source": "https://brightmill.example/careers/ap-lead", "source_date": "2026-10-20",
            "status": "ready"}
    base.update(fields)
    lines = ["## d-1 | Dana Okafor, Controller, Brightmill"] + [f"- {k}: {v}" for k, v in base.items() if v is not None]
    lines.append(f"- [{sent}] sent")
    if subject is not None:
        lines += ["", f"Subject: {subject}"]
    lines += ["", "Body:", body]
    return "\n".join(lines) + "\n"


def run(text):
    d = lint.parse_drafts(text)
    assert len(d) == 1
    return lint.lint_draft(d[0], RULES, REGISTRY, TODAY)


class CopyRules(unittest.TestCase):
    def test_good_first_touch_passes(self):
        r = run(draft())
        self.assertEqual(r["verdict"], "PASS", r["fails"])

    def test_dash_exclamation_link_fail(self):
        for bad in (" -- ", "—", "–"):
            r = run(draft(body=GOOD_BODY.replace(". When", bad + "when")))
            self.assertIn("dash", " ".join(r["fails"]))
        self.assertEqual(run(draft(body=GOOD_BODY.replace("sooner.", "sooner!")))["verdict"], "FAIL")
        r = run(draft(body=GOOD_BODY.replace("sooner.", "sooner, see www.ledgerline.example.")))
        self.assertIn("contains a link", r["fails"])

    def test_exactly_one_question_and_ends_on_it(self):
        r = run(draft(body="Is this real? " + GOOD_BODY))
        self.assertIn("2 questions, needs exactly 1", r["fails"])
        r = run(draft(body=GOOD_BODY + " Thanks."))
        self.assertIn("does not end on the question", r["fails"])

    def test_hard_word_limit(self):
        long_body = ("Finance teams grow and month end grows with them. " * 12) + "Is that you?"
        r = run(draft(body=long_body, proof=""))
        self.assertTrue(any("hard limit" in f for f in r["fails"]))

    def test_slot_and_quarantined_proof_fail(self):
        self.assertTrue(any("SLOT" in f for f in run(draft(proof="pr-03"))["fails"]))
        self.assertTrue(any("QUARANTINED" in f for f in run(draft(proof="pr-04"))["fails"]))

    def test_proof_persona_and_count(self):
        r = run(draft(persona="it_director"))
        self.assertTrue(any("not approved for persona" in f for f in r["fails"]))
        r = run(draft(proof="pr-01,pr-02"))
        self.assertTrue(any("proof lines" in f for f in r["fails"]))

    def test_unbacked_number_fails(self):
        r = run(draft(body=GOOD_BODY.replace("3 days", "5 days")))
        self.assertIn("number '5' is not in the proof line or the sourced fact", r["fails"])

    def test_first_touch_needs_source(self):
        r = run(draft(source=None, source_date=None))
        joined = " ".join(r["fails"])
        self.assertIn("no source", joined)
        self.assertIn("source_date", joined)
        r = run(draft(source_date="2026-12-01"))
        self.assertIn("source_date is in the future", r["fails"])

    def test_reply_rules(self):
        body = ("Dana, one more thought. New hires in finance usually inherit the approval process as it is. "
                "If approvals at Brightmill still run through inboxes, a short look could help. Would that be useful?")
        ok = run(draft(body=body, subject=None, thread="reply", proof="", why_now=None, source=None, source_date=None))
        self.assertEqual(ok["verdict"], "PASS", ok["fails"])
        bad = run(draft(body=body, subject="Re: hi", thread="reply", proof="", why_now=None, source=None,
                        source_date=None))
        self.assertIn("reply in thread must not have a subject", bad["fails"])

    def test_unfilled_variable(self):
        body = GOOD_BODY.replace("Hi Dana", "Hi {{first_name}}")
        self.assertEqual(run(draft(body=body, status="needs_human"))["verdict"], "NEEDS_HUMAN")
        r = run(draft(body=body, status="ready"))
        self.assertEqual(r["verdict"], "FAIL")
        r = run(draft(body=body, status="needs_human", sent="x"))
        self.assertIn("marked sent but did not pass", r["fails"])

    def test_linkedin_connect_note_limit(self):
        note = "Hi Dana, I work with finance teams on month end and saw the new distribution site. Happy to connect."
        ok = run(draft(body=note, subject=None, channel="linkedin", proof=""))
        self.assertEqual(ok["verdict"], "PASS", ok["fails"])
        r = run(draft(body=note + " More." * 60, subject=None, channel="linkedin", proof=""))
        self.assertTrue(any("characters" in f for f in r["fails"]))

    def test_missing_checkbox_and_angle(self):
        text = draft().replace("- [ ] sent\n", "")
        self.assertIn("missing '- [ ] sent' checkbox", run(text)["fails"])
        r = run(draft(angle="hype"))
        self.assertTrue(any("not in the configured angle list" in f for f in r["fails"]))

    def test_batch_angle_note(self):
        results = [{"thread": "new", "angle": "trigger"}] * 3
        self.assertTrue(lint.batch_warnings(results))
        self.assertFalse(lint.batch_warnings(results[:2] + [{"thread": "new", "angle": "referral"}]))


class FixRound(unittest.TestCase):
    def test_subject_line_is_checked(self):
        r = run(draft(subject="Close 9 days faster, guaranteed! https://x.example \u2014 act now"))
        self.assertEqual(r["verdict"], "FAIL")
        joined = " ".join(r["fails"])
        self.assertIn("subject uses an exclamation point", joined)
        self.assertIn("subject contains a link", joined)
        self.assertIn("subject uses a dash", joined)
        self.assertIn("subject number '9'", joined)

    def test_clean_subject_still_passes(self):
        self.assertEqual(run(draft(subject="Brightmill month end"))["verdict"], "PASS")

    def test_verified_proof_without_source_fails(self):
        reg = dict(REGISTRY)
        reg["pr-01"] = dict(reg["pr-01"], source="")
        fails, _ = lint.check_registry(reg)
        self.assertIn("proof 'pr-01' is VERIFIED but has no source", fails)
        d = lint.parse_drafts(draft())[0]
        r = lint.lint_draft(d, RULES, reg, TODAY)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("has no source" in f for f in r["fails"]))

    def test_example_registry_is_valid(self):
        self.assertEqual(lint.check_registry(REGISTRY)[0], [])

    def test_missing_default_proof_file_runs_with_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "gtm.json").write_text((EXAMPLE / "gtm.json").read_text())
            no_proof = ws / "d.md"
            no_proof.write_text(draft(proof=None, body=GOOD_BODY.replace(
                " Finance teams on Ledgerline close the month 3 days sooner.", "")))
            with_proof = ws / "p.md"
            with_proof.write_text(draft())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(lint.main(["--workspace", str(ws), "--drafts", str(no_proof),
                                            "--today", "2026-11-02"]), 0)
            self.assertIn("no proof registry", out.getvalue())
            self.assertFalse((ws / "outreach").exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lint.main(["--workspace", str(ws), "--drafts", str(with_proof),
                                            "--today", "2026-11-02"]), 1)
            with self.assertRaises(SystemExit):
                lint.main(["--workspace", str(ws), "--drafts", str(no_proof),
                           "--proof", str(ws / "missing.json")])

    def test_bom_files_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bom.md"
            f.write_text("\ufeff" + draft(), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lint.main(["--workspace", str(EXAMPLE), "--drafts", str(f),
                                            "--today", "2026-11-02"]), 0)


class Sequences(unittest.TestCase):
    def test_example_sequence_passes(self):
        data = json.loads((EXAMPLE / "outreach/sequences.json").read_text())
        results = lint.lint_sequences(data, RULES, REGISTRY, TODAY)
        self.assertTrue(all(r["verdict"] == "PASS" for r in results), [r for r in results if r["fails"]])

    def test_undeclared_variable_and_order(self):
        data = json.loads((EXAMPLE / "outreach/sequences.json").read_text())
        seq = data["sequences"][0]
        seq["steps"][2]["body"] += " {{mystery}}"
        seq["steps"][0]["thread"] = "reply"
        del seq["stop_rules"]
        fails = [f for r in lint.lint_sequences(data, RULES, REGISTRY, TODAY) for f in r["fails"]]
        self.assertIn("variable 'mystery' is not declared", fails)
        self.assertIn("first step must start a new thread", fails)
        self.assertIn("sequence is missing 'stop_rules'", fails)


PROBE_1 = ("Hi Dana, I noticed your team has been researching AP automation tools lately and saw the AP lead "
           "opening. Most teams we work with close three days faster and cut invoice costs in half. Is month end "
           "speed a priority for you this quarter?")
PROBE_2 = ("Hi Sarah, congrats on Brightmill's recent funding round and the new CFO hire. When a finance team "
           "grows, month end often gets slower before it gets faster. Is close speed something you are working "
           "on this quarter?")


class TruthChecks(unittest.TestCase):
    """The two probe drafts from the Oct 22 quality review both passed before these checks."""

    def test_intent_words_fail(self):
        r = run(draft(body=PROBE_1, proof=""))
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("research interest" in f for f in r["fails"]), r["fails"])

    def test_spelled_out_numbers_must_be_backed(self):
        r = run(draft(body=PROBE_1, proof=""))
        joined = " ".join(r["fails"])
        self.assertIn("'three'", joined)
        self.assertIn("'half'", joined)

    def test_seller_claim_without_proof_needs_a_human(self):
        body = ("Hi Dana, I saw Brightmill posted an opening for an AP lead on October 20. Teams like yours "
                "usually feel month end first when the team grows. Is close speed something you are working on?")
        r = run(draft(body=body, proof=""))
        self.assertEqual(r["verdict"], "NEEDS_HUMAN", r["fails"])
        self.assertTrue(any("seller claim" in w for w in r["warns"]), r["warns"])

    def test_greeting_must_match_the_person(self):
        r = run(draft(body=PROBE_2, proof=""))
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("greets 'Sarah'" in f for f in r["fails"]), r["fails"])

    def test_facts_not_in_why_now_need_a_human(self):
        r = run(draft(body=PROBE_2.replace("Hi Sarah", "Hi Dana"), proof=""))
        self.assertEqual(r["verdict"], "NEEDS_HUMAN", r["fails"])
        self.assertTrue(any("funding" in w for w in r["warns"]), r["warns"])

    def test_ordinary_phrases_are_not_false_alarms(self):
        # Oct 22 check finding: these good drafts failed or needed a human for no reason.
        opener = "Hi Dana, I saw Brightmill posted an opening for an AP lead on October 20. "
        for ask in ("Worth a two-minute look at how approvals run today?",
                    "Does month end get harder in the second half of the year?",
                    "Hiring year-round tends to strain approvals. Is that true for you?",
                    "Worth looking into before the new lead starts?"):
            r = run(draft(body=opener + ask, proof=""))
            self.assertEqual(r["verdict"], "PASS", (ask, r["fails"], r["warns"]))

    def test_greeting_allows_a_short_form_a_generic_hello_and_accents(self):
        tail = ", I saw Brightmill posted an opening for an AP lead on October 20. Is close speed on your list?"
        cases = {"Robert Whitfield": "Hi Rob", "Dana Okafor": "Hi there", "Jose Ruiz": "Hi José",
                 "José Ruiz": "Hi Jose"}
        for person, hello in cases.items():
            text = draft(body=hello + tail, proof="").replace("Dana Okafor", person)
            r = run(text)
            self.assertEqual(r["verdict"], "PASS", (person, hello, r["fails"]))

    def test_an_accented_wrong_name_is_still_caught(self):
        tail = ", I saw Brightmill posted an opening for an AP lead on October 20. Is close speed on your list?"
        r = run(draft(body="Hi Zoë" + tail, proof=""))
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("greets 'Zoë'" in f for f in r["fails"]), r["fails"])

    def test_book_gate_blocks_people_who_may_not_be_emailed(self):
        book = {"p-014": {"send_ok": "no", "followup_ok": "no", "call_ok": "yes", "linkedin_ok": "yes",
                          "send_block_reason": "status do_not_contact"}}
        d = lint.parse_drafts(draft())[0]
        r = lint.lint_draft(d, RULES, REGISTRY, TODAY, book=book)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("status do_not_contact" in f for f in r["fails"]), r["fails"])
        missing = lint.lint_draft(lint.parse_drafts(draft(person_id="p-999"))[0], RULES, REGISTRY, TODAY, book=book)
        self.assertTrue(any("not in book/people.csv" in f for f in missing["fails"]), missing["fails"])

    def test_cli_reads_the_book_when_it_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "book").mkdir()
            (ws / "book/people.csv").write_text("person_id,send_ok,followup_ok,call_ok,linkedin_ok,send_block_reason\n"
                                                "p-014,no,no,yes,yes,tag opted_out\n")
            f = ws / "drafts.md"
            f.write_text(draft())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = lint.main(["--workspace", str(ws), "--config", str(EXAMPLE / "gtm.json"),
                                  "--proof", str(EXAMPLE / "outreach/proof.json"), "--drafts", str(f),
                                  "--today", "2026-11-02"])
        self.assertEqual(code, 1)
        self.assertIn("tag opted_out", out.getvalue())


class ExampleAndCli(unittest.TestCase):
    def test_example_batch_verdicts(self):
        text = (EXAMPLE / "outreach/drafts/2026-11-02.md").read_text()
        verdicts = {d["id"]: lint.lint_draft(d, RULES, REGISTRY, TODAY)["verdict"] for d in lint.parse_drafts(text)}
        self.assertEqual(verdicts, {"d-001": "PASS", "d-002": "PASS", "d-003": "FAIL", "d-004": "FAIL",
                                    "d-005": "NEEDS_HUMAN", "d-006": "PASS", "d-007": "FAIL"})

    def test_cli_exit_code_and_report_guard(self):
        args = ["--workspace", str(EXAMPLE), "--drafts", str(EXAMPLE / "outreach/drafts/2026-11-02.md"),
                "--today", "2026-11-02"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lint.main(args), 1)
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.md"
            good.write_text(draft())
            report = Path(tmp) / "lint-report.md"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lint.main(["--workspace", str(EXAMPLE), "--drafts", str(good),
                                            "--today", "2026-11-02", "--report", str(report)]), 0)
            self.assertIn("PASS 1", report.read_text())
            before = good.read_text()
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                lint.main(["--workspace", str(EXAMPLE), "--drafts", str(good), "--report", str(good)])
            self.assertEqual(good.read_text(), before)


if __name__ == "__main__":
    unittest.main()


spec_rs = importlib.util.spec_from_file_location("record_sent", SKILL / "scripts/record_sent.py")
record_sent = importlib.util.module_from_spec(spec_rs)
spec_rs.loader.exec_module(record_sent)


class RecordSent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "gtm"
        (self.ws / "outreach" / "drafts").mkdir(parents=True)
        (self.ws / "gtm.json").write_text((EXAMPLE / "gtm.json").read_text())
        ticked = draft(sent="x", account_id="A01", sequence="seq-1", step="1")
        unticked = draft(sent=" ").replace("## d-1 |", "## d-2 |")
        self.drafts = self.ws / "outreach" / "drafts" / "2026-11-02.md"
        self.drafts.write_text("# Drafts 2026-11-02\n\n" + ticked + "\n" + unticked)

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = record_sent.main(["--workspace", str(self.ws), "--drafts", str(self.drafts),
                                     "--today", "2026-11-02", *extra])
        return code, out.getvalue()

    def log_rows(self):
        return record_sent.read_log(self.ws / "log" / "activity.csv")

    def test_ticked_draft_becomes_one_sent_row_and_reruns_add_nothing(self):
        self.assertEqual(self.run_it("--utc-offset=-05:00")[0], 0)
        rows = self.log_rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["activity_id"], r["person_id"], r["account_id"], r["channel"], r["outcome"]),
                         ("draft-2026-11-02-d-1", "p-014", "A01", "email", "sent"))
        self.assertEqual((r["sequence"], r["step"], r["angle"], r["direction"]), ("seq-1", "1", "trigger", "out"))
        self.assertEqual(r["timestamp"], "2026-11-02T12:00:00-05:00")
        self.assertIn("approximate", r["notes"])
        self.run_it("--utc-offset=-05:00")
        self.assertEqual(len(self.log_rows()), 1)

    def test_exact_send_time_and_dry_run(self):
        code, text = self.run_it("--sent-at", "2026-11-02T09:15:00-05:00", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Would record 1", text)
        self.assertFalse((self.ws / "log" / "activity.csv").exists())
        self.run_it("--sent-at", "2026-11-02T09:15:00-05:00")
        r = self.log_rows()[0]
        self.assertEqual(r["timestamp"], "2026-11-02T09:15:00-05:00")
        self.assertNotIn("approximate", r["notes"])

    def test_send_time_without_offset_is_refused(self):
        self.assertEqual(self.run_it("--sent-at", "2026-11-02T09:15:00")[0], 2)
        self.assertFalse((self.ws / "log" / "activity.csv").exists())
