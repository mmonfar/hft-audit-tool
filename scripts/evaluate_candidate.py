"""Run the test gate on ONE hand-written candidate. Standard library only. No model call here.
A runner (real or stub) is passed in: runner(version, split, candidate) -> result dict.
This script writes a gate_results row. It writes only 'reject' or 'eligible'. It never approves.
Approval and the agent_versions row come from a human step (a later card).
All gate numbers are PROPOSALS for the owner. Not a medical device. PCCP used as a design reference only."""
import argparse
import datetime
import importlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import improve_gate as g  # noqa: E402
import log  # noqa: E402

DEFAULT_SETTINGS = {"alpha": 0.05, "max_candidates": 3, "correction": "bonferroni", "need_runs": 2,
                    "false_alarm_per_30": 1, "time_pct": 25, "max_lessons": 10}


def _reject(cand, protocol_id, reasons, stopped=False, B=0, C=0, p=1.0, min_b=None, settings=None):
    return {"candidate_id": cand.get("candidate_id", "?"), "verdict": "reject", "B": B, "C": C, "p": p,
            "reasons": reasons, "stopped": stopped, "protocol_id": protocol_id, "min_b": min_b,
            "settings": settings}


def _write_row(con, res):
    con.executescript(g.IMPROVE_SCHEMA.read_text(encoding="utf-8"))
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    con.execute("INSERT INTO gate_results (candidate_id, verdict, b, c, p, reasons, protocol_id, ts)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (res["candidate_id"], res["verdict"], res["B"], res["C"], res["p"],
                 json.dumps(res["reasons"]), res["protocol_id"], ts))
    con.commit()


def evaluate(cand, runner, *, con, protocol_id, rule_files, canaries, case_texts,
             active_lessons=0, candidates_so_far=0):
    """Run the gate. Return the result dict and write one gate_results row."""
    res = _evaluate(cand, runner, con, protocol_id, rule_files, canaries, case_texts,
                    active_lessons, candidates_so_far)
    assert res["verdict"] in ("reject", "eligible")  # the gate never approves
    _write_row(con, res)
    return res


def _evaluate(cand, runner, con, protocol_id, rule_files, canaries, case_texts, active_lessons, so_far):
    # 1. hash chain, before any run (R9)
    try:
        g.check_chain(con)
        S = g.load_settings(con, protocol_id)  # 2. settings from the protocol row, hash checked (R14)
    except g.GateRefusal as e:
        return _reject(cand, protocol_id, [f"REFUSED: {e}"])
    k = S["max_candidates"]
    if so_far >= k:
        return _reject(cand, protocol_id, [f"{k} candidates already tried this round; the cap is {k}"], settings=S)
    ok, why = g.check_candidate(cand, case_texts, active_lessons, S)
    if not ok:
        return _reject(cand, protocol_id, why, settings=S)
    hits = g.canary_scan({"candidate": cand.get("text", "")}, canaries)
    if hits:
        return _reject(cand, protocol_id, [f"canary found in {n}; run stopped" for n, _ in hits], True, settings=S)

    start = g.hash_files(rule_files)
    min_b = g.min_b_to_pass(S["alpha"], k)

    def run(version, split):
        out = runner(version, split, cand)
        bad = g.validate_result(out, f"{version}/{split}")
        if bad:
            raise ValueError(bad)
        return out

    try:
        old_dev = run("old", "dev_check")
        misses = sum(not g.is_found(r, S["need_runs"]) for r in old_dev["faults"].values())
        if misses < min_b:  # R13: the set is too small for any change to pass
            return _reject(cand, protocol_id,
                           [f"cannot pass, only {misses} misses; grow the set first "
                            f"(smallest B that can pass is {min_b}; this is a proposal)"], min_b=min_b, settings=S)
        new_dev = run("new", "dev_check")
        old_reg = run("old", "regression")
        new_reg = run("new", "regression")
    except (OSError, ValueError, KeyError, TypeError) as e:
        return _reject(cand, protocol_id, [f"NOT CHECKED: {e}"], min_b=min_b, settings=S)

    for r, label in ((old_dev, "old/dev_check"), (new_dev, "new/dev_check"),
                     (old_reg, "old/regression"), (new_reg, "new/regression")):
        hits = g.canary_scan(r.get("artifacts") or {}, canaries)
        if hits:
            return _reject(cand, protocol_id, [f"canary found in {label} {n}; run stopped" for n, _ in hits],
                           True, min_b=min_b, settings=S)
    if set(old_dev["faults"]) != set(new_dev["faults"]) or set(old_reg["faults"]) != set(new_reg["faults"]):
        return _reject(cand, protocol_id, ["NOT CHECKED: old and new results cover different fault items"],
                       min_b=min_b, settings=S)

    table = g.paired_table(old_dev["faults"], new_dev["faults"], S["need_runs"])
    reg = g.paired_table(old_reg["faults"], new_reg["faults"], S["need_runs"])
    worse = g.must_not_worsen(old_dev, new_dev, S, start, g.hash_files(rule_files))
    verdict, reasons = g.decide(table, reg, worse, S)
    p = g.mcnemar_exact_one_sided(table["B"], table["C"])
    return {"candidate_id": cand.get("candidate_id", "?"), "verdict": verdict, "B": table["B"], "C": table["C"],
            "p": p, "reasons": reasons, "stopped": False, "protocol_id": protocol_id, "min_b": min_b,
            "settings": S}


def format_result(res):
    S = res.get("settings") or {}
    out = [f"Candidate {res['candidate_id']}: {res['verdict'].upper()}"]
    if res["verdict"] == "eligible":
        out.append("ELIGIBLE only. NOT approved. A human must read the diff and the results and approve.")
    out.append(f"Gains B={res['B']}, losses C={res['C']}, exact one-sided p={res['p']:.4f}")
    if res.get("min_b"):
        out.append(f"Smallest B that can pass: {res['min_b']}")
    for r in res["reasons"]:
        out.append(f"- {r}")
    if S:
        out.append(f"Settings (proposal for the owner, read from protocol {res['protocol_id']}): "
                   f"alpha {S['alpha']}, max {S['max_candidates']} candidates per round, Bonferroni.")
    else:
        out.append("All gate numbers are a proposal for the owner.")
    return "\n".join(out)


# ---------------------------------------------------------------- practice set (recorded results only)
def load_case_texts(cases_dir):
    texts = []
    for f in sorted(Path(cases_dir).glob("*")):
        if f.suffix in (".json", ".txt") and "expected" not in f.name and f.name != "EXPECTED_HASH.json":
            texts.append(f.read_text(encoding="utf-8"))
    return texts


def run_practice_set(cases_dir, record_path):
    """Run the gate on the 20 practice cases from a RECORDED result. No model. Old and new are the
    same record, so the gate only tests whether a change could pass at all."""
    cases_dir, record_path = Path(cases_dir), Path(record_path)
    cand = {"candidate_id": "PRACTICE", "kind": "prompt_line", "target": "finder",
            "text": "Practice-set size check only."}
    con = log.open_db(":memory:")
    log.store_protocol(con, "P-GATE", json.dumps(DEFAULT_SETTINGS, sort_keys=True), "2026-11-10T00:00:00")
    con.executescript(g.IMPROVE_SCHEMA.read_text(encoding="utf-8"))

    def runner(version, split, c):
        try:
            rec = json.loads(record_path.read_text(encoding="utf-8"))
            exp_hash = json.loads((cases_dir / "EXPECTED_HASH.json").read_text(encoding="utf-8"))["files"]
            for name, h in exp_hash.items():
                if g.sha256((cases_dir / name).read_text(encoding="utf-8")) != h:
                    raise ValueError(f"expected answer file {name} was changed")
            per = rec["per_case"]
        except (OSError, KeyError, ValueError) as e:
            raise ValueError(f"recorded pilot result cannot be read: {e}")
        ok = {"found": True, "quote": "recorded", "rule_id": "recorded"}
        no = {"found": False, "quote": "", "rule_id": ""}
        faults = {c_["case_id"]: [ok if c_["outcome"] == "found" else no] * 3 for c_ in per if c_["group"] == "fault"}
        clean = {c_["case_id"]: [{"flagged": c_["outcome"] == "false_alarm"}] * 3 for c_ in per if c_["group"] == "clean"}
        unable = [c_ for c_ in per if c_["group"] == "unreadable"]
        return {"faults": faults, "clean": clean, "unable_rate": len(unable) / max(1, len(per)),
                "plants": {"fake_quote": [True] * 3, "unreadable": [True] * 3}, "minutes_per_case": 3.3,
                "artifacts": {}}

    res = evaluate(cand, runner, con=con, protocol_id="P-GATE", rule_files=[], canaries=[],
                   case_texts=[], active_lessons=0, candidates_so_far=0)
    con.close()
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the test gate on one candidate. Never approves.")
    ap.add_argument("--practice", action="store_true", help="run on the 20 practice cases from the recorded result")
    ap.add_argument("--cases-dir", default=str(ROOT / "pilot" / "cases"))
    ap.add_argument("--record", default=str(ROOT / "pilot" / "pilot_result.json"))
    ap.add_argument("--candidate", help="path to the hand-written candidate JSON")
    ap.add_argument("--runner", help="module:function of the runner (real or stub)")
    ap.add_argument("--db", help="log database file (needs the protocol row)")
    ap.add_argument("--protocol", default="P-GATE")
    ap.add_argument("--rule-file", action="append", default=[], help="code-rule file to hash (repeat)")
    ap.add_argument("--canary", action="append", default=[], help="canary string (repeat)")
    ap.add_argument("--active-lessons", type=int, default=0)
    ap.add_argument("--tried-this-round", type=int, default=0)
    a = ap.parse_args(argv)
    if a.practice:
        res = run_practice_set(a.cases_dir, a.record)
    else:
        if not (a.candidate and a.runner and a.db):
            ap.error("--candidate, --runner and --db are needed (or use --practice)")
        mod, fn = a.runner.split(":")
        runner = getattr(importlib.import_module(mod), fn)
        cand = json.loads(Path(a.candidate).read_text(encoding="utf-8"))
        con = log.open_db(a.db, create=False)
        res = evaluate(cand, runner, con=con, protocol_id=a.protocol, rule_files=a.rule_file,
                       canaries=a.canary, case_texts=load_case_texts(a.cases_dir),
                       active_lessons=a.active_lessons, candidates_so_far=a.tried_this_round)
        con.close()
    print(format_result(res))
    return 0 if res["verdict"] == "eligible" else 1


if __name__ == "__main__":
    sys.exit(main())
