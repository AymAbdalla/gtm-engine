#!/usr/bin/env python3
"""Check outreach drafts and sequence templates against the copy rules.

Reads gtm.json (the `copy` section), the proof registry and either a drafts
file, a sequences file, or both. Prints PASS, NEEDS_HUMAN or FAIL per draft
with reasons. Exit code 1 when any draft or template step fails.

The script only checks. It never writes drafts, never sends anything and
never changes its inputs. It can write one Markdown report with --report.
"""

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_COPY = {
    "min_words": 25,
    "max_words": 60,
    "hard_max_words": 85,
    "questions": 1,
    "end_on_question": True,
    "banned": ["em_dash", "exclamation", "links"],
    "banned_phrases": ["just checking in", "circle back", "touch base", "hope this finds you well"],
    "max_proof_lines": 1,
    "connect_note_max_chars": 300,
    "proof_max_age_days": 365,
    "angles": [],
    # Truth checks (Oct 22 review). Each list is an editable default in gtm.json `copy`.
    "intent_words": ["researching", "been looking into", "been looking at", "visited our",
                     "on our website", "your team has been reading", "intent data", "in-market",
                     "showed interest in"],
    # Phrases that contain a number word but claim no number ("second half of the year").
    "number_ok_phrases": ["first half", "second half"],
    "number_words": ["two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "dozen",
                     "twice", "double", "doubled", "triple", "tripled", "half", "percent"],
    "claim_phrases": ["teams we work with", "teams like yours", "companies like yours", "our customers",
                      "our clients", "customers see", "we help", "we helped", "most teams we"],
    "fact_words": ["raised", "funding", "round", "acquired", "acquisition", "named", "appointed", "hired",
                   "hire", "promoted", "joined", "ipo", "launched", "expanded"],
}

DASH = re.compile("[\u2014\u2013]| -- ")
LINK = re.compile(r"https?://|www\.", re.I)
PRONOUN = re.compile(r"\b(he|she|him|her|his|hers|himself|herself)\b", re.I)
VAR = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’&./-]*")
NUMBER = re.compile(r"\d[\d,.]*")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELD = re.compile(r"^-\s+([a-z_]+):\s*(.*)$")
GREETING = re.compile(r"^(?:hi|hello|hey|dear)\s+([^\W\d_][\w'’-]*)\s*[,.!]", re.I)
# "Hi there" and "Hi team" greet nobody in particular: no name to check.
GENERIC_GREETINGS = {"there", "team", "all", "everyone", "folks", "both"}
# Short forms that are not a prefix of the full name. A prefix ("Rob" for Robert) is always fine.
NICKNAMES = {"bob": "robert", "bill": "william", "liz": "elizabeth", "beth": "elizabeth",
             "betty": "elizabeth", "kate": "katherine", "katie": "katherine", "jim": "james",
             "jack": "john", "dick": "richard", "peggy": "margaret", "maggie": "margaret",
             "chuck": "charles", "ted": "edward", "ned": "edward", "hank": "henry", "sasha": "alexander"}
SENT = re.compile(r"^-\s+\[( |x|X)\]\s+sent\s*$")
CHANNELS = {"email", "linkedin", "call"}
THREADS = {"new", "reply"}


def load_json(path, label):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise SystemExit(f"{label} not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} is not valid JSON: {path}: {exc}")


def copy_rules(config):
    rules = dict(DEFAULT_COPY)
    rules.update((config or {}).get("copy", {}))
    return rules


def load_registry(data):
    entries = data.get("entries", data if isinstance(data, list) else [])
    registry = {}
    for e in entries:
        if "id" in e:
            registry[str(e["id"])] = e
    return registry


def words(text):
    return WORD.findall(text)


def parse_date(value):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_drafts(text):
    """Split a drafts file into draft dicts. See references/drafts-format.md."""
    drafts, current, mode = [], None, None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if current:
                drafts.append(current)
            head = line[3:].strip()
            current = {"id": head.split("|")[0].strip(), "heading": head, "fields": {},
                       "subject": None, "body_lines": [], "sent": None}
            mode = "fields"
            continue
        if current is None:
            continue
        if mode == "body":
            current["body_lines"].append(raw)
            continue
        m = SENT.match(line)
        if m:
            current["sent"] = m.group(1).lower() == "x"
            continue
        m = FIELD.match(line)
        if m and mode == "fields":
            current["fields"][m.group(1)] = m.group(2).strip()
            continue
        if line.startswith("Subject:"):
            current["subject"] = line[len("Subject:"):].strip()
            continue
        if line.strip() == "Body:":
            mode = "body"
            continue
    if current:
        drafts.append(current)
    for d in drafts:
        d["body"] = "\n".join(d.pop("body_lines")).strip()
    return drafts


def check_banned(text, rules, where=""):
    """Banned items and phrases. Used on the body and on the subject line."""
    fails = []
    banned = set(rules.get("banned", []))
    if "em_dash" in banned and DASH.search(text):
        fails.append(f"{where}uses a dash as punctuation (em dash, en dash or ' -- ')")
    if "exclamation" in banned and "!" in text:
        fails.append(f"{where}uses an exclamation point")
    if "links" in banned and LINK.search(text):
        fails.append(f"{where}contains a link")
    if "gendered_pronouns" in banned and PRONOUN.search(text):
        fails.append(f"{where}uses a gendered pronoun")
    low = text.lower()
    for phrase in rules.get("banned_phrases", []):
        if phrase.lower() in low:
            fails.append(f"{where}banned phrase: '{phrase}'")
    return fails


def check_text(body, rules, channel, thread):
    """Rules that look only at the message text."""
    fails, warns = check_banned(body, rules), []
    if channel == "call":
        return fails, warns
    connect_note = channel == "linkedin" and thread == "new"
    questions = body.count("?")
    if connect_note:
        limit = int(rules.get("connect_note_max_chars", 300))
        if len(body) > limit:
            fails.append(f"connect note is {len(body)} characters, limit {limit}")
        if questions > int(rules.get("questions", 1)):
            fails.append(f"{questions} questions, limit {rules.get('questions', 1)}")
        return fails, warns
    n = len(words(body))
    if n > int(rules["hard_max_words"]):
        fails.append(f"{n} words, hard limit {rules['hard_max_words']}")
    elif n > int(rules["max_words"]):
        warns.append(f"{n} words, aim for {rules['min_words']} to {rules['max_words']}")
    elif n < int(rules["min_words"]):
        warns.append(f"{n} words, aim for {rules['min_words']} to {rules['max_words']}")
    want = int(rules.get("questions", 1))
    if questions != want:
        fails.append(f"{questions} questions, needs exactly {want}")
    if rules.get("end_on_question", True) and want and not body.rstrip().endswith("?"):
        fails.append("does not end on the question")
    return fails, warns


def check_proof(proof_ids, persona, registry, rules, today):
    fails, warns, texts = [], [], []
    limit = int(rules.get("max_proof_lines", 1))
    if len(proof_ids) > limit:
        fails.append(f"{len(proof_ids)} proof lines, limit {limit}")
    max_age = rules.get("proof_max_age_days")
    for pid in proof_ids:
        entry = registry.get(pid)
        if entry is None:
            fails.append(f"proof '{pid}' is not in the registry")
            continue
        status = str(entry.get("status", "")).upper()
        if status != "VERIFIED":
            fails.append(f"proof '{pid}' is {status or 'missing a status'}; only VERIFIED proof can be used")
            continue
        if not str(entry.get("source", "")).strip():
            fails.append(f"proof '{pid}' is VERIFIED but has no source; it cannot be used")
        allowed = entry.get("personas") or []
        if allowed and "all" not in allowed and persona not in allowed:
            fails.append(f"proof '{pid}' is not approved for persona '{persona or 'unknown'}'")
        verified = parse_date(entry.get("verified_date"))
        if verified is None:
            fails.append(f"proof '{pid}' has no verified_date")
        elif today and max_age and (today - verified).days > int(max_age):
            warns.append(f"proof '{pid}' was verified {(today - verified).days} days ago; re-check it")
        texts.append(str(entry.get("text", "")))
    return fails, warns, texts


def _has_word(text, phrase):
    """The phrase as whole words. A hyphen joins words, so 'two' is not found in
    'two-minute' and 'round' is not found in 'year-round'."""
    return re.search(r"(?<![A-Za-z-])" + re.escape(phrase.lower()) + r"(?![A-Za-z-])", text.lower()) is not None


def _fold(name):
    """Lowercase without accents, so José and Jose are the same name."""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).lower()


def _same_person(greeted, first):
    g, f = _fold(greeted), _fold(first)
    return g == f or (len(g) >= 3 and f.startswith(g)) or NICKNAMES.get(g) == f


def check_truth(body, f, heading, rules, proof_ids, allowed_texts):
    """Checks that look at what the message claims, not only how it reads.
    Returns (fails, holds): holds make the draft NEEDS_HUMAN, never PASS."""
    fails, holds = [], []
    text = VAR.sub("", body)
    for phrase in rules.get("intent_words", []):
        if _has_word(text, phrase):
            fails.append(f"hints at research interest ('{phrase}'): intent is timing only, never mentioned")
            break
    backing = " ".join(allowed_texts).lower()
    counted = text
    for phrase in rules.get("number_ok_phrases", []):
        counted = re.sub(re.escape(phrase), " ", counted, flags=re.I)
    for word in rules.get("number_words", []):
        if _has_word(counted, word) and not _has_word(backing, word):
            fails.append(f"number word '{word}' is not in the proof line or the sourced fact")
    if not proof_ids:
        for phrase in rules.get("claim_phrases", []):
            if _has_word(text, phrase):
                holds.append(f"possible seller claim ('{phrase}') with no proof: add a VERIFIED proof or cut it")
                break
    why = f.get("why_now", "")
    for word in rules.get("fact_words", []):
        if _has_word(text, word) and not _has_word(why, word):
            holds.append(f"mentions '{word}', which the why_now fact does not: open the source and check it")
    greet = GREETING.match(body.strip())
    name = heading.split("|", 1)[1].strip().split(",")[0].split() if "|" in heading else []
    if greet and name and not name[0].startswith("(") and greet.group(1).lower() not in GENERIC_GREETINGS:
        if not _same_person(greet.group(1), name[0]):
            fails.append(f"greets '{greet.group(1)}' but the draft is for {name[0]}")
    return fails, holds


def check_book(f, channel, thread, book):
    """When book/people.csv exists, the draft's person must pass that channel's gate."""
    if book is None:
        return []
    pid = f.get("person_id", "")
    row = book.get(pid)
    if row is None:
        return [f"person {pid} is not in book/people.csv: rebuild the book or fix the id"]
    if channel == "email":
        col = "send_ok" if thread == "new" else "followup_ok"
    else:
        col = {"call": "call_ok", "linkedin": "linkedin_ok"}.get(channel, "")
    if col and col in row and row[col] != "yes":
        why = row.get(col.replace("_ok", "_block_reason"), "") or row.get("send_block_reason", "")
        return [f"book says {col} is {row[col] or 'blank'}" + (f" ({why})" if why else "")]
    return []


def load_book(path):
    if not path.is_file():
        return None
    import csv
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {r.get("person_id", ""): r for r in csv.DictReader(fh)}


def check_numbers(body, allowed_texts, where=""):
    """Every number in the message must come from used proof or the sourced fact."""
    allowed = {n.strip(".,") for t in allowed_texts for n in NUMBER.findall(t)}
    fails = []
    for token in sorted(set(n.strip(".,") for n in NUMBER.findall(VAR.sub("", body)))):
        if token and token not in allowed:
            fails.append(f"{where}number '{token}' is not in the proof line or the sourced fact")
    return fails


def check_registry(registry):
    """Entries that can never be used safely. Reported as one result row."""
    fails, warns = [], []
    for pid, e in sorted(registry.items()):
        status = str(e.get("status", "")).upper()
        if status not in {"VERIFIED", "SLOT", "QUARANTINED"}:
            fails.append(f"proof '{pid}' has status '{status or 'missing'}'; use VERIFIED, SLOT or QUARANTINED")
        elif status == "VERIFIED":
            if not str(e.get("source", "")).strip():
                fails.append(f"proof '{pid}' is VERIFIED but has no source")
            if not str(e.get("text", "")).strip():
                fails.append(f"proof '{pid}' is VERIFIED but has no text")
            if parse_date(e.get("verified_date")) is None:
                fails.append(f"proof '{pid}' is VERIFIED but has no verified_date")
    return fails, warns


def lint_draft(d, rules, registry, today, book=None):
    f = d["fields"]
    fails, warns = [], []
    channel = f.get("channel", "").lower()
    thread = f.get("thread", "").lower()
    status = f.get("status", "ready").lower()
    body = d["body"]
    if channel not in CHANNELS:
        fails.append(f"channel must be one of {sorted(CHANNELS)}")
    if thread not in THREADS:
        fails.append(f"thread must be one of {sorted(THREADS)}")
    if not body:
        fails.append("empty body")
    if not f.get("person_id"):
        fails.append("missing person_id")
    angles = rules.get("angles") or []
    if not f.get("angle"):
        fails.append("missing angle tag")
    elif angles and f["angle"] not in angles:
        fails.append(f"angle '{f['angle']}' is not in the configured angle list")
    subject = d["subject"]
    if channel == "email":
        if thread == "new" and not subject:
            fails.append("new email thread needs a subject")
        if thread == "reply" and subject:
            fails.append("reply in thread must not have a subject")
    elif subject:
        fails.append(f"{channel} drafts have no subject")
    if thread == "new" and channel in {"email", "linkedin"}:
        if not f.get("why_now"):
            fails.append("first touch has no why_now fact")
        src = f.get("source", "")
        if not src:
            fails.append("first touch has no source")
        sdate = f.get("source_date", "")
        if not ISO_DATE.match(sdate):
            fails.append("first touch needs source_date as YYYY-MM-DD")
        elif today and parse_date(sdate) and parse_date(sdate) > today:
            fails.append("source_date is in the future")
    text_fails, text_warns = check_text(body, rules, channel, thread)
    fails += text_fails
    warns += text_warns
    proof_ids = [p.strip() for p in f.get("proof", "").split(",") if p.strip()]
    p_fails, p_warns, proof_texts = check_proof(proof_ids, f.get("persona", ""), registry, rules, today)
    fails += p_fails
    warns += p_warns
    allowed_numbers = proof_texts + [f.get("why_now", ""), f.get("source_date", "")]
    fails += check_numbers(body, allowed_numbers)
    if subject:
        fails += check_banned(subject, rules, "subject ")
        fails += check_numbers(subject, allowed_numbers, "subject ")
    truth_fails, holds = check_truth(body + " " + (subject or ""), f, d["heading"], rules, proof_ids,
                                     allowed_numbers)
    fails += truth_fails
    fails += check_book(f, channel, thread, book)
    warns += holds
    unfilled = sorted(set(VAR.findall(body + " " + (subject or ""))))
    if unfilled and status != "needs_human":
        fails.append(f"unfilled variables {unfilled} but status is not needs_human")
    if d["sent"] is None:
        fails.append("missing '- [ ] sent' checkbox")
    if fails:
        verdict = "FAIL"
    elif unfilled or status == "needs_human" or holds:
        verdict = "NEEDS_HUMAN"
    else:
        verdict = "PASS"
    if d["sent"] and verdict != "PASS":
        fails.append("marked sent but did not pass")
        verdict = "FAIL"
    if verdict == "NEEDS_HUMAN" and unfilled:
        warns.append(f"fill {unfilled} before it can be sent")
    return {"id": d["id"], "heading": d["heading"], "verdict": verdict, "fails": fails, "warns": warns,
            "angle": f.get("angle", ""), "thread": thread}


def batch_warnings(results):
    firsts = [r["angle"] for r in results if r["thread"] == "new" and r["angle"]]
    if len(firsts) >= 3 and len(set(firsts)) == 1:
        return [f"every first touch in this batch uses the '{firsts[0]}' angle; vary angles across the batch"]
    return []


def lint_sequences(data, rules, registry, today):
    results = []
    seqs = data.get("sequences", data if isinstance(data, list) else [])
    for seq in seqs:
        sid = seq.get("id", "?")
        declared = seq.get("variables", {}) or {}
        examples = {k: str(v.get("example", "")) if isinstance(v, dict) else "" for k, v in declared.items()}
        persona = seq.get("persona", "")
        used = set()
        head = {"id": sid, "heading": f"sequence {sid} (setup)", "verdict": "PASS", "fails": [], "warns": [],
                "angle": "", "thread": ""}
        for key in ("who", "angle", "stop_rules", "steps"):
            if not seq.get(key):
                head["fails"].append(f"sequence is missing '{key}'")
        for k, v in declared.items():
            if not isinstance(v, dict) or not v.get("description") or not v.get("example"):
                head["fails"].append(f"variable '{k}' needs a description and an example")
        last_day = 0
        steps = sorted(seq.get("steps", []), key=lambda s: (s.get("day", 0), s.get("order", 0)))
        for i, step in enumerate(steps):
            label = f"{sid} day {step.get('day')} {step.get('channel', '?')}"
            fails, warns = [], []
            channel = str(step.get("channel", "")).lower()
            thread = str(step.get("thread", "")).lower()
            if i == 0 and thread != "new":
                fails.append("first step must start a new thread")
            day = step.get("day")
            if not isinstance(day, int) or day < 1:
                fails.append("day must be a whole number from 1")
            elif day < last_day:
                fails.append("days go backwards")
            else:
                last_day = day
            for text in (step.get("subject") or "", step.get("body") or ""):
                for var in VAR.findall(text):
                    used.add(var)
                    if var not in declared:
                        fails.append(f"variable '{var}' is not declared")
            subject = VAR.sub(lambda m: examples.get(m.group(1), m.group(0)), step.get("subject") or "")
            body = VAR.sub(lambda m: examples.get(m.group(1), m.group(0)), step.get("body") or "")
            if channel not in CHANNELS:
                fails.append(f"channel must be one of {sorted(CHANNELS)}")
            if channel == "email" and thread == "new" and not subject:
                fails.append("new email thread needs a subject")
            if channel == "email" and thread == "reply" and subject:
                fails.append("reply in thread must not have a subject")
            if channel != "email" and subject:
                fails.append(f"{channel} steps have no subject")
            t_fails, t_warns = check_text(body, rules, channel, thread)
            fails += t_fails
            warns += t_warns
            proof_ids = [p for p in ([step["proof"]] if isinstance(step.get("proof"), str)
                                     else step.get("proof", [])) if p]
            p_fails, p_warns, texts = check_proof(proof_ids, persona, registry, rules, today)
            fails += p_fails
            warns += p_warns
            fails += check_numbers(body, texts + list(examples.values()))
            if subject:
                fails += check_banned(subject, rules, "subject ")
                fails += check_numbers(subject, texts + list(examples.values()), "subject ")
            results.append({"id": label, "heading": f"sequence {label}", "verdict": "FAIL" if fails else "PASS",
                            "fails": fails, "warns": warns, "angle": "", "thread": thread})
        for k in declared:
            if k not in used:
                head["warns"].append(f"variable '{k}' is declared but never used")
        head["verdict"] = "FAIL" if head["fails"] else "PASS"
        results.insert(len(results) - len(steps), head)
    return results


def render(results, extra_warns):
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("PASS", "NEEDS_HUMAN", "FAIL")}
    lines = [f"PASS {counts['PASS']}  NEEDS_HUMAN {counts['NEEDS_HUMAN']}  FAIL {counts['FAIL']}", ""]
    for r in results:
        lines.append(f"{r['verdict']:<11} {r['heading']}")
        for msg in r["fails"]:
            lines.append(f"    fail: {msg}")
        for msg in r["warns"]:
            lines.append(f"    note: {msg}")
    for msg in extra_warns:
        lines.append(f"batch note: {msg}")
    return "\n".join(lines), counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default="gtm", help="GTM workspace folder (default ./gtm)")
    ap.add_argument("--config", help="gtm.json path (default <workspace>/gtm.json)")
    ap.add_argument("--proof", help="proof registry (default <workspace>/outreach/proof.json)")
    ap.add_argument("--drafts", help="drafts Markdown file to check")
    ap.add_argument("--sequences", help="sequences.json to check")
    ap.add_argument("--today", help="YYYY-MM-DD for date checks (default: today)")
    ap.add_argument("--book", help="prospect book for the gate check (default <workspace>/book/people.csv if it exists)")
    ap.add_argument("--report", help="also write the result as Markdown to this path")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    config_path = Path(args.config) if args.config else ws / "gtm.json"
    proof_path = Path(args.proof) if args.proof else ws / "outreach" / "proof.json"
    if not args.drafts and not args.sequences:
        ap.error("give --drafts, --sequences, or both")
    config = load_json(config_path, "config") if config_path.exists() else {}
    rules = copy_rules(config)
    extra = []
    if proof_path.exists():
        registry = load_registry(load_json(proof_path, "proof registry"))
    elif args.proof:
        raise SystemExit(f"proof registry not found: {proof_path}")
    else:
        registry = {}
        extra.append(f"no proof registry at {proof_path}; any proof line fails as unregistered")
    today = parse_date(args.today) if args.today else dt.date.today()
    if args.today and today is None:
        ap.error("--today must be YYYY-MM-DD")

    inputs = [p for p in (config_path, proof_path, args.drafts, args.sequences) if p]
    if args.report and any(Path(args.report).resolve() == Path(p).resolve() for p in inputs):
        ap.error("--report must not point at an input file")

    results = []
    reg_fails, reg_warns = check_registry(registry)
    if reg_fails or reg_warns:
        results.append({"id": "registry", "heading": f"proof registry {proof_path}",
                        "verdict": "FAIL" if reg_fails else "PASS", "fails": reg_fails, "warns": reg_warns,
                        "angle": "", "thread": ""})
    if args.sequences:
        results += lint_sequences(load_json(args.sequences, "sequences"), rules, registry, today)
    if args.drafts:
        try:
            text = Path(args.drafts).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise SystemExit(f"drafts file not found: {args.drafts}")
        drafts = parse_drafts(text)
        if not drafts:
            raise SystemExit("no drafts found (each draft starts with '## ')")
        book_path = Path(args.book) if args.book else ws / "book" / "people.csv"
        book = load_book(book_path)
        if book is None:
            extra.append(f"no prospect book at {book_path}: the send gate was not checked")
        draft_results = [lint_draft(d, rules, registry, today, book=book) for d in drafts]
        extra += batch_warnings(draft_results)
        results += draft_results

    text, counts = render(results, extra)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text("# Copy check\n\n```\n" + text + "\n```\n", encoding="utf-8")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
