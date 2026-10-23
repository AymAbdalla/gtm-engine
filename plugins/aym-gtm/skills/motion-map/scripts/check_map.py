#!/usr/bin/env python3
"""Check a sales motion map and write a readable map with one automation pick.

Reads <workspace>/motion/map.json (stages, roles and systems) and writes:

  <out>/map.md     Mermaid flow, stage cards, RACI, exceptions, waste, readiness,
                   decision ownership, the one step to automate first and its loop check
  <out>/checks.md  graph and rule findings, items that could not be checked, and
                   unresolved references (always listed, even when empty)

A map is "clean" only with zero findings and zero unchecked items.
Exit code: 0 clean, 1 not clean, 2 input error.

Standard library only. No network. Never changes a tool, a CRM or a schedule.
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULTS = {
    "max_nodes": 15,
    "risk_order": ["low", "medium", "high"],
    "pick_exclude_risk": ["high"],
    "require_else_branch": True,
    "loop_max_identical_runs": 3,
    "accept_share_floor": 0.5,
}
STAGE_KINDS = ("task", "decision")
TRIGGERS = ("clock", "event", "human")
WORK = ("mechanical", "judgment")
TIERS = ("automatic", "batch", "manual", "blocked")
LEVELS = ("none", "observe", "suggest", "draft")
ROLE_KINDS = ("human", "scheduled_builder", "executor")
WASTE = ("waiting", "rework", "handoff", "manual", "none")
DECISION_OWNERS = ("rule", "model", "human")
ELSE_WORDS = ("else", "otherwise", "anything else")
TOP_LEVEL = LEVELS[-1]
READINESS_QUESTIONS = (
    "What can be seen today: which fields, lists and logs exist now?",
    "What is missing: fields, owners, statuses or ids? Write an empty list when nothing is missing.",
    "What must be cleaned first, and in what order?",
)


class InputError(Exception):
    pass


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and Path(path).is_file():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise InputError(f"{path} is not valid JSON: {exc}") from exc
        section = raw.get("motion", {}) if isinstance(raw, dict) else {}
        if not isinstance(section, dict):
            raise InputError("gtm.json: motion must be an object")
        cfg.update(section)
    if not isinstance(cfg["max_nodes"], int) or cfg["max_nodes"] < 3:
        raise InputError("motion.max_nodes must be a whole number of 3 or more")
    return cfg


def load_map(path):
    p = Path(path)
    if not p.is_file():
        raise InputError(f"no map at {p}. Write motion/map.json first (see references/map-format.md).")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("stages"), list) or not data["stages"]:
        raise InputError("map.json needs a non-empty stages list")
    seen = set()
    for s in data["stages"]:
        if not isinstance(s, dict) or not s.get("id"):
            raise InputError("every stage needs an id")
        if s["id"] in seen:
            raise InputError(f"stage id {s['id']} appears twice")
        seen.add(s["id"])
    return data


def _num(v, default=0.0):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def readiness_known(stage):
    """Readiness counts as known only when the stage says what can be seen today (a non-empty
    visible_today) and what is missing (a list; an empty list means nothing is missing). A block with
    every list empty says nothing, so it stays unknown."""
    rd = stage.get("readiness")
    return (isinstance(rd, dict) and isinstance(rd.get("missing"), list)
            and bool(_list(rd.get("visible_today"))))


class Result:
    def __init__(self):
        self.findings = []    # (code, where, message)
        self.unchecked = []   # (where, what could not be checked)
        self.unresolved = []  # (where, reference)

    def find(self, code, where, msg):
        self.findings.append((code, where, msg))

    def skip(self, where, msg):
        self.unchecked.append((where, msg))

    def ref(self, where, msg):
        self.unresolved.append((where, msg))

    @property
    def clean(self):
        return not self.findings and not self.unchecked


def edges(stage):
    out = []
    for e in _list(stage.get("next")):
        if isinstance(e, str):
            out.append({"to": e, "when": ""})
        elif isinstance(e, dict):
            out.append({"to": e.get("to", ""), "when": str(e.get("when", "") or "")})
    return out


SEND_WORDS = ("sequencer", "email", "inbox", "mailbox", "calendar", "dialer", "sms", "linkedin")


def sends_or_books(system):
    """A live system that sends messages or books time: marked `sends: true`, or named like one."""
    if not isinstance(system, dict) or not system.get("live"):
        return False
    if "sends" in system:
        return bool(system["sends"])
    text = f"{system.get('id', '')} {system.get('label', '')}".lower()
    return any(w in text for w in SEND_WORDS)


def apply_measures(m, log_path, today, weeks=4):
    """For stages with a `measure` block, replace volume_per_week with a count from the
    activity log over the last `weeks` weeks. Measured stages are labelled as such."""
    measured = [s for s in m["stages"] if isinstance(s.get("measure"), dict)]
    if not measured or not log_path.exists():
        return 0
    with log_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    start = today - timedelta(weeks=weeks)
    for s in measured:
        rule = s["measure"]
        outcomes = set(_list(rule.get("outcomes")))
        n = 0
        for r in rows:
            try:
                day = datetime.fromisoformat((r.get("timestamp") or "").strip()).date()
            except ValueError:
                continue
            if not (start < day <= today):
                continue
            if rule.get("channel") and r.get("channel") != rule["channel"]:
                continue
            if rule.get("direction") and r.get("direction") != rule["direction"]:
                continue
            if outcomes and r.get("outcome") not in outcomes:
                continue
            n += 1
        s["volume_per_week"] = round(n / weeks, 1)
        s["_measured"] = True
    return len(measured)


def analyze(m, cfg):
    r = Result()
    stages = {s["id"]: s for s in m["stages"]}
    order = [s["id"] for s in m["stages"]]
    roles = {x.get("id"): x for x in _list(m.get("roles")) if isinstance(x, dict)}
    systems = {x.get("id"): x for x in _list(m.get("systems")) if isinstance(x, dict)}
    start = m.get("start") or order[0]
    ends = set(_list(m.get("ends")))

    # Graph: references and edges.
    if start not in stages:
        r.ref("map", f"start stage {start!r} does not exist")
        r.find("G1", "map", f"start stage {start!r} does not exist")
    for e in sorted(ends):
        if e not in stages:
            r.ref("map", f"end stage {e!r} does not exist")
            r.find("G1", "map", f"end stage {e!r} does not exist")
    incoming = {sid: [] for sid in order}
    for sid in order:
        for e in edges(stages[sid]):
            if e["to"] not in stages:
                r.ref(sid, f"edge to missing stage {e['to']!r}")
                r.find("G1", sid, f"edge points to stage {e['to']!r}, which does not exist")
            else:
                incoming[e["to"]].append(sid)
    for sid in order:
        if sid != start and not incoming[sid]:
            r.find("G2", sid, "no way in: nothing leads to this stage")
        if sid not in ends and not [e for e in edges(stages[sid]) if e["to"] in stages]:
            r.find("G2", sid, "no way out: this stage leads nowhere and is not marked as an end")

    # Decisions need real branches.
    for sid in order:
        s = stages[sid]
        if s.get("kind", "task") not in STAGE_KINDS:
            r.find("R0", sid, f"kind must be one of {', '.join(STAGE_KINDS)}")
        if s.get("kind") != "decision":
            continue
        branches = edges(s)
        if len(branches) < 2:
            r.find("G3", sid, f"decision has {len(branches)} branch(es); it needs at least 2")
        for b in branches:
            if not b["when"].strip():
                r.find("G3", sid, f"branch to {b['to']!r} has no condition")
        if cfg["require_else_branch"] and not any(b["when"].strip().lower() in ELSE_WORDS for b in branches):
            r.find("G3", sid, "no branch for anything else: add one with when \"else\"")

    # Cut-off clusters: stages the start cannot reach.
    if start in stages:
        seen, todo = {start}, [start]
        while todo:
            cur = todo.pop()
            for e in edges(stages[cur]):
                if e["to"] in stages and e["to"] not in seen:
                    seen.add(e["to"])
                    todo.append(e["to"])
        cut = [sid for sid in order if sid not in seen]
        if cut:
            r.find("G4", ", ".join(cut), "cut off: the start stage can never reach these stages")

    # Roles and systems.
    for rid, role in sorted(roles.items(), key=lambda kv: str(kv[0])):
        if role.get("kind") not in ROLE_KINDS:
            r.find("R0", f"role {rid}", f"kind must be one of {', '.join(ROLE_KINDS)}")
    for sys_id, sysd in sorted(systems.items(), key=lambda kv: str(kv[0])):
        op = sysd.get("operator")
        if not op:
            r.find("R1", f"system {sys_id}", "no operator: name the one role that writes to this system")
        elif op not in roles:
            r.ref(f"system {sys_id}", f"operator {op!r} is not a role")
            r.find("R1", f"system {sys_id}", f"operator {op!r} is not a defined role")

    for sid in order:
        s = stages[sid]
        raci = s.get("raci") if isinstance(s.get("raci"), dict) else {}
        doer = raci.get("r") or s.get("owner")
        for label, rid in (("owner", s.get("owner")), ("raci.r", raci.get("r")), ("raci.a", raci.get("a"))):
            if rid and rid not in roles:
                r.ref(sid, f"{label} {rid!r} is not a role")
                r.find("R1", sid, f"{label} {rid!r} is not a defined role")
        for rid in _list(raci.get("c")) + _list(raci.get("i")):
            if rid not in roles:
                r.ref(sid, f"raci role {rid!r} is not a role")
                r.find("R1", sid, f"RACI names {rid!r}, which is not a defined role")
        for sys_id in _list(s.get("systems")) + _list(s.get("writes")):
            if sys_id not in systems:
                r.ref(sid, f"system {sys_id!r} is not defined")
                r.find("R1", sid, f"system {sys_id!r} is not defined")
        for sys_id in _list(s.get("writes")):
            sysd = systems.get(sys_id)
            if sysd and sysd.get("operator") and doer and doer != sysd["operator"]:
                r.find("R1", sid, f"{doer} writes to {sys_id}, but its one operator is {sysd['operator']}")
            role = roles.get(doer, {})
            if sysd and sysd.get("live") and role.get("kind") == "scheduled_builder":
                r.find("R3", sid, f"the scheduled builder writes to live system {sys_id}; it may only write files")

        # Stage card completeness.
        trig = s.get("trigger") if isinstance(s.get("trigger"), dict) else {}
        if trig.get("type") not in TRIGGERS:
            r.skip(sid, "trigger type missing (clock, event or human)")
        if not s.get("owner"):
            r.skip(sid, "no owner")
        if s.get("work") not in WORK:
            r.skip(sid, "work type missing (mechanical or judgment)")
        auto = s.get("automation") if isinstance(s.get("automation"), dict) else {}
        tier, level = auto.get("tier"), auto.get("level", "none")
        if tier not in TIERS:
            r.skip(sid, "automation tier missing (automatic, batch, manual or blocked)")
        if level not in LEVELS:
            r.find("R0", sid, f"automation level must be one of {', '.join(LEVELS)}")
        if s.get("waste", "none") not in WASTE:
            r.find("R0", sid, f"waste must be one of {', '.join(WASTE)}")

        # Writing to a live tool that sends, books or messages can't be undone unless the map
        # says why not (irreversible_override with a reason).
        sends = [w for w in _list(s.get("writes")) if sends_or_books(systems.get(w))]
        if sends and not s.get("irreversible") and not str(s.get("irreversible_override") or "").strip():
            r.find("R2", sid, f"writes to {', '.join(sends)}, which sends or books: mark it irreversible, "
                              "or give irreversible_override with the reason it can be undone")
        # A person commits, spends or sends.
        if s.get("irreversible"):
            if tier == "automatic":
                r.find("R2", sid, "can't be undone but runs automatically: a person must commit, spend or send")
            if not auto.get("approval_point"):
                r.find("R2", sid, "can't be undone and names no human approval point")
            if roles.get(doer, {}).get("kind") in ("scheduled_builder", "executor") and not auto.get("approval_point"):
                r.find("R2", sid, f"{doer} does something that can't be undone with no approval")
        # The executor applies approved plans only.
        if roles.get(doer, {}).get("kind") == "executor" and s.get("work") == "judgment":
            r.find("R4", sid, "the executor is doing judgment work; it may only apply approved plans")

        # Readiness ladder.
        ready = s.get("readiness")
        if not isinstance(ready, dict):
            r.skip(sid, "no readiness block (visible today, missing, cleanup)")
        elif not isinstance(ready.get("missing"), list):
            r.skip(sid, "readiness unknown: no missing list (write [] when nothing is missing)")
        elif not _list(ready.get("visible_today")):
            r.skip(sid, "readiness unknown: visible_today is empty (say what can be seen today)")
        elif tier in ("automatic", "batch") and _list(ready.get("missing")):
            r.find("R5", sid, "automated while not ready: " + "; ".join(_list(ready["missing"])))

        # Loop check for anything that runs on its own.
        if tier == "automatic":
            loop = s.get("loop")
            if not isinstance(loop, dict):
                r.skip(sid, "runs automatically but has no loop check")
            else:
                for key, msg in (("repeats_weekly", "does not repeat weekly or more"),
                                 ("auto_check", "no automatic check can fail the work"),
                                 ("budget", "no cap on runs, time or cost"),
                                 ("sees_results", "cannot see its own results")):
                    if not loop.get(key):
                        r.find("R7", sid, f"loop check fails: {msg}")
                if not loop.get("state_file"):
                    r.find("R7", sid, "loop has no state file to resume from")
                if not isinstance(loop.get("do_not_retry"), list):
                    r.find("R7", sid, "loop state has no do-not-retry list")
                k = loop.get("stop_after_identical_runs")
                if not isinstance(k, int) or k < 1 or k > cfg["loop_max_identical_runs"]:
                    r.find("R7", sid, f"loop must stop after at most {cfg['loop_max_identical_runs']} runs with no progress")

        # Decision ownership.
        if s.get("kind") == "decision":
            d = s.get("decision")
            if not isinstance(d, dict):
                r.skip(sid, "decision has no ownership test answers")
            else:
                owner = d.get("owner")
                if owner not in DECISION_OWNERS:
                    r.skip(sid, "decision owner missing (rule, model or human)")
                for key in ("exact_fact", "consequential", "if_wrong", "check", "accountable"):
                    if key not in d:
                        r.skip(sid, f"decision test answer missing: {key}")
                if owner == "model" and d.get("consequential"):
                    r.find("R6", sid, "a model owns a consequential gate; a rule or a person must own it")
                if owner == "model" and d.get("exact_fact"):
                    r.find("R6", sid, "a model owns an exact fact; a rule should own it")
                if d.get("accountable") and d["accountable"] not in roles:
                    r.ref(sid, f"accountable {d['accountable']!r} is not a role")
                    r.find("R1", sid, f"accountable {d['accountable']!r} is not a defined role")
    return r


def finding_codes_by_stage(m, res):
    """Stage id -> sorted finding codes. A G4 finding names several stages at once."""
    ids = {st["id"] for st in m["stages"]}
    by_stage = {}
    for code, where, _ in res.findings:
        for token in str(where).split(", "):
            if token in ids:
                by_stage.setdefault(token, set()).add(code)
    return {sid: sorted(codes) for sid, codes in by_stage.items()}


def pick_report(m, cfg, res=None):
    """Sort automation candidates into ready, not ready, readiness unknown and left out.

    A candidate is a mechanical task, manual or batch, that can be undone and is not excluded
    by its risk if automated wrong. Among candidates, a stage with any finding, a stage already
    at the top automation level, and a stage whose readiness is unknown can never be picked.
    """
    if res is None:
        res = analyze(m, cfg)
    flagged = finding_codes_by_stage(m, res)
    risk_rank = {k: i for i, k in enumerate(cfg["risk_order"])}
    ready, not_ready, unknown, left_out = [], [], [], []
    for s in m["stages"]:
        auto = s.get("automation") if isinstance(s.get("automation"), dict) else {}
        risk = s.get("risk") if isinstance(s.get("risk"), dict) else {}
        if (s.get("kind") == "decision" or s.get("work") != "mechanical" or s.get("irreversible")
                or auto.get("tier") not in ("manual", "batch")
                or risk.get("automated_wrong") in cfg["pick_exclude_risk"]):
            continue
        minutes = _num(s.get("volume_per_week")) * _num(s.get("minutes_per_item"))
        row = {"id": s["id"], "name": s.get("name", s["id"]), "minutes": minutes,
               "cold": _num(s.get("cold_rate")), "wrong": risk.get("automated_wrong", "unknown"),
               "manual": risk.get("left_manual", "unknown"), "level": auto.get("level", "none"),
               "volume": _num(s.get("volume_per_week")), "measured": bool(s.get("_measured"))}
        if s["id"] in flagged:
            row["why"] = "has findings (" + ", ".join(flagged[s["id"]]) + "); fix them in checks.md and rerun"
            left_out.append(row)
        elif row["level"] == TOP_LEVEL:
            row["why"] = (f"already at the top automation level ({TOP_LEVEL}); "
                          "a person keeps the final step")
            left_out.append(row)
        elif not readiness_known(s):
            unknown.append(row)
        elif s["readiness"]["missing"]:
            row["cleanup"] = _list(s["readiness"].get("cleanup")) or s["readiness"]["missing"]
            not_ready.append(row)
        else:
            ready.append(row)
    ready.sort(key=lambda x: (risk_rank.get(x["wrong"], len(risk_rank)), -x["cold"], -x["minutes"], x["id"]))
    for group in (not_ready, unknown, left_out):
        group.sort(key=lambda x: x["id"])
    return ready, not_ready, unknown, left_out


def pick_automation(m, cfg, res=None):
    ready, not_ready, _, _ = pick_report(m, cfg, res)
    return ready, not_ready


def next_level(level):
    ladder = ["none", "observe", "suggest", "draft"]
    i = ladder.index(level) if level in ladder else 0
    return ladder[min(i + 1, len(ladder) - 1)]


def _esc(text):
    return str(text).replace('"', "'").replace("|", "/").replace("\n", " ")


def mermaid(m, cfg):
    stages = {s["id"]: s for s in m["stages"]}
    order = [s["id"] for s in m["stages"]]
    degree = {sid: 0 for sid in order}
    for sid in order:
        for e in edges(stages[sid]):
            if e["to"] in stages:
                degree[sid] += 1
                degree[e["to"]] += 1
    keep = order
    note = ""
    if len(order) > cfg["max_nodes"]:
        top = sorted(order, key=lambda sid: (-degree[sid], order.index(sid)))[:cfg["max_nodes"]]
        keep = [sid for sid in order if sid in top]
        note = (f"Showing {len(keep)} of {len(order)} stages, the ones with the most connections. "
                "The stage table below lists every stage.")
    lines = ["```mermaid", "flowchart TD"]
    for sid in keep:
        s = stages[sid]
        label = _esc(f"{sid} {s.get('name', '')}".strip())
        lines.append(f'  {sid}{{"{label}"}}' if s.get("kind") == "decision" else f'  {sid}["{label}"]')
    for sid in keep:
        for e in edges(stages[sid]):
            if e["to"] in keep:
                when = _esc(e["when"]).strip()
                lines.append(f"  {sid} -->|{when}| {e['to']}" if when else f"  {sid} --> {e['to']}")
    lines.append("```")
    return "\n".join(lines), note


def _cell(v):
    if v is None or v == "" or v == []:
        return "-"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v).replace("|", "/")


def render_map(m, cfg, res):
    motion = m.get("motion") if isinstance(m.get("motion"), dict) else {}
    roles = {x.get("id"): x for x in _list(m.get("roles")) if isinstance(x, dict)}
    systems = {x.get("id"): x for x in _list(m.get("systems")) if isinstance(x, dict)}
    out = [f"# Motion map: {motion.get('name', 'unnamed motion')}", ""]
    if motion.get("summary"):
        out += [motion["summary"], ""]
    verdict = "clean" if res.clean else f"not clean: {len(res.findings)} finding(s), {len(res.unchecked)} unchecked item(s)"
    out += [f"Checks: **{verdict}**. Details in checks.md.", ""]
    flow, note = mermaid(m, cfg)
    out += ["## Flow", "", flow, ""]
    if note:
        out += [note, ""]

    out += ["## Roles and systems", "", "| Role | Kind | What it may do |", "| --- | --- | --- |"]
    may = {"human": "calls, judges, approves, sends", "scheduled_builder": "writes files and plans only, never touches live tools",
           "executor": "applies approved plans only, never writes copy or picks who to contact"}
    for rid, role in roles.items():
        out.append(f"| {_cell(rid)} | {_cell(role.get('kind'))} | {may.get(role.get('kind'), '-')} |")
    out += ["", "| System | Live | One operator |", "| --- | --- | --- |"]
    for sys_id, sysd in systems.items():
        out.append(f"| {_cell(sysd.get('label', sys_id))} | {_cell(bool(sysd.get('live')))} | {_cell(sysd.get('operator'))} |")
    out.append("")

    out += ["## Stage table", "", "| Stage | Kind | Trigger | Work | Owner | Tier | Level | Volume/week | Waste |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in m["stages"]:
        trig = s.get("trigger") if isinstance(s.get("trigger"), dict) else {}
        auto = s.get("automation") if isinstance(s.get("automation"), dict) else {}
        out.append(f"| {s['id']} {_cell(s.get('name'))} | {_cell(s.get('kind', 'task'))} | {_cell(trig.get('type'))} | "
                   f"{_cell(s.get('work'))} | {_cell(s.get('owner'))} | {_cell(auto.get('tier'))} | "
                   f"{_cell(auto.get('level', 'none'))} | {_cell(s.get('volume_per_week'))} | {_cell(s.get('waste', 'none'))} |")
    out.append("")

    out += ["## Stage cards", ""]
    for s in m["stages"]:
        trig = s.get("trigger") if isinstance(s.get("trigger"), dict) else {}
        auto = s.get("automation") if isinstance(s.get("automation"), dict) else {}
        out += [f"### {s['id']} {s.get('name', '')}".rstrip(), "",
                f"- Trigger: {_cell(trig.get('type'))}: {_cell(trig.get('detail'))}",
                f"- Work: {_cell(s.get('work'))}. Owner: {_cell(s.get('owner'))}. Can't be undone: {_cell(bool(s.get('irreversible')))}",
                f"- Inputs: {_cell(s.get('inputs'))}. Outputs: {_cell(s.get('outputs'))}",
                f"- Automation: tier {_cell(auto.get('tier'))}, level {_cell(auto.get('level', 'none'))}",
                f"- What a person reads: {_cell(auto.get('human_reads'))}",
                f"- Approval point: {_cell(auto.get('approval_point'))}",
                f"- Off switch: {_cell(auto.get('off_switch'))}",
                ""]

    out += ["## RACI", "", "| Stage | Does it (R) | Owns it (A) | Asked (C) | Told (I) |", "| --- | --- | --- | --- | --- |"]
    for s in m["stages"]:
        raci = s.get("raci") if isinstance(s.get("raci"), dict) else {}
        out.append(f"| {s['id']} | {_cell(raci.get('r'))} | {_cell(raci.get('a'))} | {_cell(raci.get('c'))} | {_cell(raci.get('i'))} |")
    out.append("")

    exc = [(s["id"], e) for s in m["stages"] for e in _list(s.get("exceptions")) if isinstance(e, dict)]
    out += ["## Exceptions", ""]
    if exc:
        out += ["| Stage | Usually | Sometimes |", "| --- | --- | --- |"]
        out += [f"| {sid} | {_cell(e.get('usually'))} | {_cell(e.get('sometimes'))} |" for sid, e in exc]
    else:
        out.append("None recorded.")
    out.append("")

    out += ["## Waste at handoffs", ""]
    tagged = [(s["id"], s.get("waste")) for s in m["stages"] if s.get("waste") and s.get("waste") != "none"]
    if tagged:
        counts = {}
        for _, w in tagged:
            counts[w] = counts.get(w, 0) + 1
        out.append(", ".join(f"{w}: {counts[w]}" for w in WASTE if w in counts) + ".")
        out += [f"- {sid}: {w}" for sid, w in tagged]
    else:
        out.append("None tagged.")
    out.append("")

    out += ["## Readiness", "", "| Stage | Visible today | Missing | Cleanup first |", "| --- | --- | --- | --- |"]
    for s in m["stages"]:
        rd = s.get("readiness") if isinstance(s.get("readiness"), dict) else {}
        missing = _cell(rd.get("missing")) if readiness_known(s) else "unknown"
        out.append(f"| {s['id']} | {_cell(rd.get('visible_today'))} | {missing} | {_cell(rd.get('cleanup'))} |")
    out.append("")

    decisions = [s for s in m["stages"] if s.get("kind") == "decision"]
    out += ["## Decision ownership", ""]
    if decisions:
        out += ["| Decision | Question | Owner | Exact fact | Consequential | If wrong | Check | Accountable |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s in decisions:
            d = s.get("decision") if isinstance(s.get("decision"), dict) else {}
            out.append(f"| {s['id']} | {_cell(d.get('question'))} | {_cell(d.get('owner'))} | {_cell(d.get('exact_fact'))} | "
                       f"{_cell(d.get('consequential'))} | {_cell(d.get('if_wrong'))} | {_cell(d.get('check'))} | {_cell(d.get('accountable'))} |")
    else:
        out.append("No decision stages.")
    out.append("")

    ready, not_ready, unknown, left_out = pick_report(m, cfg, res)
    out += ["## Automate first", ""]
    if ready:
        p = ready[0]
        if res is not None and any(c.startswith("G") for c, _, _ in res.findings):
            out += ["**Provisional:** the flow has findings (G1 to G4), so this map may not show the real work. "
                    "Fix the flow first, rerun, then trust the pick.", ""]
        measured = " (measured from the log)" if p.get("measured") else ""
        out += [f"**{p['id']} {p['name']}**: move from level {p['level']} to {next_level(p['level'])}.", "",
                f"- Repetitive: about {p['volume']:g} item{'' if p['volume'] == 1 else 's'} a week{measured}, "
                f"about {p['minutes']:g} minutes a week by hand.",
                f"- Where deals go cold: cold rate {p['cold']:g}.",
                f"- Risk if automated wrong: {p['wrong']}. Risk if left manual: {p['manual']}.",
                "- Build order: do it once by hand and watch it work, turn the steps into a skill or script, "
                "wrap it in a loop with stop rules, schedule it last.",
                "- Before it runs on a schedule, answer the loop check: does it repeat weekly or more, can an automatic "
                "check fail the work, does a budget cap retries, can it see its own results? Keep a state file with a "
                "do-not-retry list. Judge it by the share of runs whose changes are accepted; below "
                f"{cfg['accept_share_floor']:g}, fix it or turn it off.",
                ""]
        if len(ready) > 1:
            out.append("Next in line: " + "; ".join(f"{x['id']} {x['name']}" for x in ready[1:4]) + ".")
            out.append("")
    else:
        out += ["No step is ready to automate. Clean up first.", ""]
    if not_ready:
        out.append("Not ready yet (clean these first):")
        out += [f"- {x['id']} {x['name']}: {_cell(x['cleanup'])}" for x in not_ready]
        out.append("")
    if unknown:
        out.append("Readiness unknown (these can't be picked until their readiness is written down):")
        out += [f"- {x['id']} {x['name']}" for x in unknown]
        out.append("")
        out.append("Answer these for each one, add them to its readiness block in map.json, then rerun:")
        out += [f"{i}. {q}" for i, q in enumerate(READINESS_QUESTIONS, 1)]
        out.append("")
    if left_out:
        out.append("Left out of the pick:")
        out += [f"- {x['id']} {x['name']}: {x['why']}." for x in left_out]
        out.append("")
    out += ["Nothing here changes a tool, a CRM or a schedule. A person decides and builds each change.", ""]
    return "\n".join(out)


def render_checks(m, res):
    verdict = "clean" if res.clean else "not clean"
    out = ["# Map checks", "",
           f"Result: **{verdict}**. {len(res.findings)} finding(s), {len(res.unchecked)} unchecked item(s), "
           f"{len(res.unresolved)} unresolved reference(s). {len(m['stages'])} stages checked.", "",
           "A map is clean only with zero findings and zero unchecked items.", "", "## Findings", ""]
    if res.findings:
        out += ["| Code | Where | Finding |", "| --- | --- | --- |"]
        out += [f"| {c} | {_cell(w)} | {_cell(msg)} |" for c, w, msg in res.findings]
    else:
        out.append("None.")
    out += ["", "## Not checked", ""]
    out += [f"- {w}: {msg}" for w, msg in res.unchecked] or ["None."]
    out += ["", "## Unresolved references", ""]
    out += [f"- {w}: {msg}" for w, msg in res.unresolved] or ["None."]
    out += ["", "Codes: G1 missing reference, G2 no way in or out, G3 decision branches, G4 cut off, "
            "R0 bad value, R1 roles and one operator per system, R2 a person commits, spends or sends, "
            "R3 builder touches a live tool, R4 executor doing judgment work, R5 automated while not ready, "
            "R6 decision ownership, R7 loop check.", ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a sales motion map and write map.md and checks.md.")
    ap.add_argument("--workspace", default="gtm", help="GTM workspace folder (default ./gtm)")
    ap.add_argument("--map", help="map file (default <workspace>/motion/map.json)")
    ap.add_argument("--config", help="gtm.json (default <workspace>/gtm.json)")
    ap.add_argument("--out", help="folder for map.md and checks.md (default <workspace>/motion)")
    ap.add_argument("--today", help="YYYY-MM-DD for measured volumes (default: today)")
    args = ap.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        ap.error("--today must be YYYY-MM-DD")
    ws = Path(args.workspace)
    map_path = Path(args.map) if args.map else ws / "motion" / "map.json"
    out_dir = Path(args.out) if args.out else ws / "motion"
    try:
        cfg = load_config(Path(args.config) if args.config else ws / "gtm.json")
        m = load_map(map_path)
        targets = [out_dir / "map.md", out_dir / "checks.md"]
        if any(t.resolve() == map_path.resolve() for t in targets):
            raise InputError("refusing to write over the input map")
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    apply_measures(m, ws / "log" / "activity.csv", today)
    res = analyze(m, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "map.md").write_text(render_map(m, cfg, res), encoding="utf-8")
    (out_dir / "checks.md").write_text(render_checks(m, res), encoding="utf-8")
    ready, not_ready, unknown, left_out = pick_report(m, cfg, res)
    print(f"Checked {len(m['stages'])} stages: {'clean' if res.clean else 'not clean'} "
          f"({len(res.findings)} findings, {len(res.unchecked)} unchecked, {len(res.unresolved)} unresolved).")
    provisional = any(c.startswith("G") for c, _, _ in res.findings)
    if ready:
        print(f"Automate first{' (provisional: fix the flow first)' if provisional else ''}: "
              f"{ready[0]['id']} {ready[0]['name']}.")
    else:
        print("No step is ready to automate yet.")
    if unknown:
        print(f"Readiness unknown for {len(unknown)} stage(s): answer the readiness questions in map.md.")
    if left_out:
        print(f"Left out of the pick: {len(left_out)} stage(s) with findings or already at the top level.")
    print(f"Wrote {out_dir / 'map.md'} and {out_dir / 'checks.md'}. Nothing was changed in any tool.")
    return 0 if res.clean else 1


if __name__ == "__main__":
    sys.exit(main())
