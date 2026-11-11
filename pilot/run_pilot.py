"""20-case pilot runner (development cases only, synthetic).

python pilot/run_pilot.py --stub            fake model, fast (used by the tests)
python pilot/run_pilot.py                   real gpt-oss:20b on 127.0.0.1, one call at a time, keep_alive 0

Saves a result file after each case (pilot/results/<case>.json). Run it again and it skips the
cases already saved, so a stop loses at most the one case that was running.
Counts only. No accuracy figure, no percent. Every figure is labelled PILOT.
Standard library only. Exit: 0 ok, 2 refused (bad case set or edited expected file), 3 run stopped.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import log  # noqa: E402
import orchestrator  # noqa: E402
import referee  # noqa: E402

PILOT_LABEL = "PILOT, 20 made-up development cases, one run"
GROUPS = ("fault", "clean", "unreadable", "trap_fake_quote", "trap_repeat")
FORBIDDEN = ("accuracy", "percent", "kappa", "pct")
KEPT = ("CONFIRMED", "DISPUTED")
REPEAT_TEXT = ("The dose is too high for this patient. The dose is too high for this patient. "
               "Please check the dose again.")


class Refused(Exception):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def say(msg):
    print(f"[{stamp()}] {msg}", flush=True)


# ---------------------------------------------------------------- case set
def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check_expected_hash(cdir):
    """Problems (list of text) between the recorded hashes and the expected files now."""
    cdir = Path(cdir)
    hf = cdir / "EXPECTED_HASH.json"
    if not hf.is_file():
        return ["EXPECTED_HASH.json is missing"]
    rec = json.loads(hf.read_text(encoding="utf-8"))
    bad = []
    for name, sha in rec["files"].items():
        f = cdir / name
        if not f.is_file() or sha_file(f) != sha:
            bad.append(f"{name}: expected file changed after it was hashed")
    on_disk = {p.name for p in cdir.glob("*.expected.json")}
    if on_disk != set(rec["files"]):
        bad.append("expected files on disk differ from the hash list")
    return bad


def load_cases(cdir):
    """Load the case set. Raises Refused for anything not split=dev or any file named heldout."""
    cdir = Path(cdir)
    names = [p.name for p in cdir.iterdir()]
    if any("heldout" in n.lower() or "held-out" in n.lower() or "held_out" in n.lower() for n in names):
        raise Refused("a file named held-out is in the case folder")
    cases = []
    for f in sorted(cdir.glob("P*.json")):
        if f.name.endswith(".expected.json"):
            continue
        c = json.loads(f.read_text(encoding="utf-8"))
        if c.get("split") != "dev":
            raise Refused(f"{c.get('case_id', f.name)}: split is not dev")
        ocr_file = cdir / f"{c['case_id']}.ocr.txt"
        exp_file = cdir / f"{c['case_id']}.expected.json"
        if not ocr_file.is_file() or not exp_file.is_file():
            raise Refused(f"{c['case_id']}: OCR text file or expected file is missing")
        c["ocr_text"] = ocr_file.read_bytes().decode("utf-8")
        c["expected"] = json.loads(exp_file.read_text(encoding="utf-8"))
        c["expected_sha256"] = sha_file(exp_file)
        cases.append(c)
    return cases


# ---------------------------------------------------------------- models
class PilotStub:
    """Fake model for --stub: answers what the expected file says. Proves the plumbing only."""
    tag = "stub"

    def __init__(self, case):
        self.case = case

    def generate(self, agent, prompt, seed=0):
        if agent == "reader":
            return "PASS\n" + self.case["ocr_text"], False
        e = self.case["expected"]
        if agent == "rule_checker" and self.case["group"] == "fault":
            q = e["expected_quotes"][0]
            return json.dumps([dict(fault_id="f1", rule_id=e["rule_id"], quote=q, location="line",
                                    severity="major", confidence=0.8, audience="nurse")]), False
        return "[]", False

    def name_next_check(self, kind, options):
        return None


class TrapModel:
    """Plants a trap in the rule checker's answer. The reader still runs on the inner model."""

    def __init__(self, inner, trap):
        self.inner, self.trap, self.tag = inner, trap, inner.tag

    def generate(self, agent, prompt, seed=0):
        if agent != "rule_checker":
            return self.inner.generate(agent, prompt, seed)
        if self.trap["type"] == "fake_quote":
            if "The referee dropped" in prompt:
                return "[]", False
            return json.dumps([dict(fault_id="trap1", rule_id=self.trap["rule_id"], quote=self.trap["quote"],
                                    location="line 1", severity="major", confidence=0.9,
                                    audience="nurse")]), False
        return REPEAT_TEXT, False

    def name_next_check(self, kind, options):
        return self.inner.name_next_check(kind, options)


class LoggedModel:
    """Writes a line to the log file before and after every model call."""

    def __init__(self, inner, case_id):
        self.inner, self.case_id, self.tag = inner, case_id, inner.tag

    def generate(self, agent, prompt, seed=0):
        say(f"CALL START case={self.case_id} agent={agent} prompt_chars={len(prompt)}")
        t = time.time()
        try:
            out = self.inner.generate(agent, prompt, seed)
        except Exception as e:
            say(f"CALL FAILED case={self.case_id} agent={agent} {type(e).__name__}: {e}")
            raise
        say(f"CALL DONE case={self.case_id} agent={agent} seconds={time.time() - t:.0f} reply_chars={len(out[0])}")
        return out

    def name_next_check(self, kind, options):
        say(f"CALL START case={self.case_id} agent=next_check")
        t = time.time()
        r = self.inner.name_next_check(kind, options)
        say(f"CALL DONE case={self.case_id} agent=next_check seconds={time.time() - t:.0f}")
        return r


def make_model(case, stub):
    inner = PilotStub(case) if stub else orchestrator.LocalModel()
    if case.get("trap"):
        inner = TrapModel(inner, case["trap"])
    return LoggedModel(inner, case["case_id"])


def models_ok(tags):
    """Only gpt-oss:20b (or the stub tag) may appear in the models table."""
    return set(tags) <= {"gpt-oss:20b", "stub"}


# ---------------------------------------------------------------- scoring
def _overlap(a, b):
    a, b = referee.fix_space(a), referee.fix_space(b)
    return bool(a) and bool(b) and (a in b or b in a)


def score_case(expected, result):
    """Compare the final state with the written expected answer. Returns dict(outcome, extra_kept)."""
    g = expected["group"]
    kept = result.get("findings") or []
    state = result["state"]
    if g == "fault":
        hits = [k for k in kept if k["rule_id"] == expected["rule_id"]
                and any(_overlap(k["quote"], q) for q in expected["expected_quotes"])]
        return dict(outcome="found" if hits else "missed", extra_kept=len(kept) - (1 if hits else 0))
    if g == "unreadable":
        return dict(outcome="correct_unable" if state == "UNABLE TO CHECK" else "WRONG_CLEAN",
                    extra_kept=len(kept))
    if g == "trap_fake_quote":
        leaked = any(_overlap(k["quote"], expected["trap_quote"]) for k in kept)
        dropped = any(_overlap(d.get("quote") or "", expected["trap_quote"]) for d in result.get("dropped") or [])
        return dict(outcome="trap_caught" if dropped and not leaked and not kept else "trap_failed",
                    extra_kept=len(kept))
    if g == "trap_repeat":
        ok = state == "UNABLE TO CHECK" and "repeat" in (result.get("reason") or "")
        return dict(outcome="trap_caught" if ok else "trap_failed", extra_kept=len(kept))
    # clean
    if state == "UNABLE TO CHECK":
        return dict(outcome="unable_unexpected", extra_kept=0)
    return dict(outcome="correct_clean" if not kept else "false_alarm", extra_kept=len(kept))


def forbidden_keys(obj):
    """Every key (any depth) that names accuracy, percent, kappa."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(w in str(k).lower() for w in FORBIDDEN):
                found.append(k)
            found += forbidden_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found += forbidden_keys(v)
    return found


def tally(per_case):
    n = len(per_case)
    nf = sum(1 for c in per_case if c["group"] == "fault")

    def fig(v, d):
        return dict(value=f"{v} of {d}", label=PILOT_LABEL)

    return dict(
        found=fig(sum(c["outcome"] == "found" for c in per_case), nf if nf else 12),
        missed=fig(sum(c["outcome"] == "missed" for c in per_case), nf if nf else 12),
        false_alarms=fig(sum(c["extra_kept"] > 0 for c in per_case), 20),
        unable_to_check=fig(sum(c["final"]["state"] == "UNABLE TO CHECK" for c in per_case), 20),
        clean_cases_left_clean=fig(sum(c["outcome"] == "correct_clean" for c in per_case), 4),
        unreadable_cases_unable=fig(sum(c["outcome"] == "correct_unable" for c in per_case), 2),
        traps_caught=fig(sum(c["outcome"] == "trap_caught" for c in per_case), 2),
    )


# ---------------------------------------------------------------- note check
def note_problems(text):
    need = ["PILOT", "does not replace a human factors engineer", "not a medical device", "NOT REVIEWED",
            "15 to 20 minutes per case-run", "5 to 7 hours"]
    return [f"missing: {n}" for n in need if n not in text]


# ---------------------------------------------------------------- run
def write_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_result(out, cases, status, started):
    per = []
    for c in cases:
        f = out / "results" / f"{c['case_id']}.json"
        if f.is_file():
            per.append(json.loads(f.read_text(encoding="utf-8")))
    result = dict(label=PILOT_LABEL, status=status, cases_done=len(per), cases_total=len(cases),
                  started_at=started, updated_at=stamp(),
                  note="Pre-check only. Does not replace a human factors engineer. Not a medical device. NOT REVIEWED.",
                  counts=tally(per) if per else {}, per_case=per)
    write_json(out / "pilot_result.json", result)
    return result


def copy_db(src, dst):
    a = sqlite3.connect(src)
    b = sqlite3.connect(dst)
    a.backup(b)
    b.close()
    a.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the 20-case pilot (dev cases only).")
    ap.add_argument("--stub", action="store_true", help="fake model")
    ap.add_argument("--cases-dir", default=str(HERE / "cases"))
    ap.add_argument("--out-dir", default=str(HERE))
    ap.add_argument("--stop-after", type=int, default=0, help="stop after N new cases (test of resume)")
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    try:
        bad = check_expected_hash(a.cases_dir)
        if bad:
            raise Refused("; ".join(bad))
        cases = load_cases(a.cases_dir)
        if len(cases) != 20:
            raise Refused(f"expected 20 cases, found {len(cases)}")
    except (Refused, OSError, ValueError, KeyError) as e:
        say(f"REFUSED: {e}. No model was called.")
        return 2
    (out / "results").mkdir(parents=True, exist_ok=True)
    started = stamp()
    dated = json.loads((Path(a.cases_dir) / "EXPECTED_HASH.json").read_text(encoding="utf-8"))["dated_at"]
    say(f"START pilot cases={len(cases)} mode={'stub' if a.stub else 'real gpt-oss:20b'} out={out} "
        f"expected_dated_at={dated}")
    con = log.open_db(str(out / "pilot_run.sqlite"))
    new = 0
    try:
        for c in cases:
            if (out / "results" / f"{c['case_id']}.json").is_file():
                say(f"SKIP case={c['case_id']} already saved")
                continue
            if a.stop_after and new >= a.stop_after:
                break
            say(f"CASE START {c['case_id']} group={c['group']}")
            run_input = {k: v for k, v in c.items() if k not in ("expected", "expected_sha256", "group", "trap")}
            res = orchestrator.run_case(run_input, con, make_model(c, a.stub),
                                        host_note=f"pilot expected_sha256={c['expected_sha256']}")
            final = dict(state=res["state"], findings=res["findings"], dropped=res["dropped"],
                         reason=res["reason"], message=res["message"])
            sc = score_case(c["expected"], final)
            write_json(out / "results" / f"{c['case_id']}.json",
                       dict(case_id=c["case_id"], group=c["group"], expected=c["expected"], final=final,
                            outcome=sc["outcome"], extra_kept=sc["extra_kept"], run_id=res["run_id"],
                            finished_at=stamp()))
            new += 1
            r = write_result(out, cases, "RUNNING", started)
            say(f"CASE DONE {c['case_id']} outcome={sc['outcome']} saved={r['cases_done']} of {len(cases)}")
    except Exception as e:  # the case that was running is lost; the saved ones stay
        say(f"RUN STOPPED: {type(e).__name__}: {e}. Run the same command again to resume.")
        write_result(out, cases, "RUNNING", started)
        con.close()
        return 3
    con.commit()
    con.close()
    done = len(list((out / "results").glob("P*.json")))
    complete = done == len(cases)
    r = write_result(out, cases, "COMPLETE" if complete else "RUNNING", started)
    if complete:
        copy_db(out / "pilot_run.sqlite", out / "audit_log_pilot.sqlite")
        say("COMPLETE: result file and audit_log_pilot.sqlite written")
    else:
        say(f"PAUSED at {r['cases_done']} of {len(cases)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
