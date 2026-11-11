"""Orchestrator: one case through reader -> rule checker -> referee, every call logged to SQLite.

CLI: python orchestrator.py --case <file> --db <file> [--stub] [--stub-dir <dir>] [--seed N]
                            [--heldout] [--repeat N]
Standard library only. The only network address ever used is 127.0.0.1:11434 (local model server).
Real model: gpt-oss:20b, keep_alive 0, one job at a time.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import log
import referee

ROOT = Path(__file__).resolve().parent
FRAMEWORK = ROOT / "framework" / "hf_framework_v0.json"
MODEL_TAG = "gpt-oss:20b"
LOCAL_HOST, LOCAL_PORT = "127.0.0.1", 11434
DESIGN_VERSION = "team-v1"
NUM_PREDICT = 1500
UNABLE_TEXT = "COULD NOT CHECK"
MAX_RETRY = 1  # send-backs per dropped finding. Set here, in code, not in a prompt.
# Fixed next-check list by case type. The model may name one item; it cannot add one. First item = default.
CHECKS = {
    "label": ["check_abbreviation_list", "check_unit_format", "check_look_alike_names"],
    "alert": ["check_dismiss_button", "check_alert_wording", "check_abbreviation_list"],
}


def check_options(kind):
    return CHECKS.get(kind) or CHECKS["label"]


def choose_next_check(kind, named):
    """Return (check, refused). A name outside the list for this case type is refused: default used."""
    options = check_options(kind)
    if named is None or named == "":
        return options[0], False
    if isinstance(named, str) and named.strip() in options:
        return named.strip(), False
    return options[0], True


class CaseRefused(Exception):
    pass


# ---------------------------------------------------------------- models
class StubModel:
    """Fake local model: fixed outputs from files. <agent>.txt, or <agent>.<n>.txt for the n-th try."""
    tag = "stub"

    def __init__(self, folder):
        self.folder = Path(folder)
        self.calls = {}

    def generate(self, agent, prompt, seed=0):
        n = self.calls[agent] = self.calls.get(agent, 0) + 1
        f = self.folder / f"{agent}.{n}.txt"
        if not f.is_file():
            f = self.folder / f"{agent}.txt"
        if not f.is_file():
            raise FileNotFoundError(f"stub output missing: {f.name}")
        text = f.read_text(encoding="utf-8")
        hit = text.rstrip().endswith(referee.LIMIT_MARK)
        return text.replace(referee.LIMIT_MARK, "").rstrip("\n"), hit

    def name_next_check(self, kind, options):
        """The check the stub names, from next_check.txt. None if the file is absent."""
        f = self.folder / "next_check.txt"
        return f.read_text(encoding="utf-8").strip() if f.is_file() else None


class LocalModel:
    """gpt-oss:20b through the local model server on 127.0.0.1 only. keep_alive 0. One job at a time."""
    tag = MODEL_TAG

    def __init__(self, host=LOCAL_HOST, port=LOCAL_PORT, timeout=900):
        if host != "127.0.0.1":
            raise ValueError("The local model server must be on 127.0.0.1 only")
        self.url = f"http://{host}:{port}/api/generate"
        self.timeout = timeout

    def generate(self, agent, prompt, seed=0):
        import urllib.request  # only ever used with the loopback url built in __init__
        body = json.dumps({"model": MODEL_TAG, "prompt": prompt, "stream": False, "keep_alive": 0,
                           "options": {"temperature": 0, "seed": seed, "num_predict": NUM_PREDICT}}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("response", ""), data.get("done_reason") == "length"

    def name_next_check(self, kind, options):
        """Ask the model to name ONE check from the list. Any failure = None (the default is used)."""
        try:
            out, _ = self.generate("next_check", "Name one item from this list and nothing else: " + ", ".join(options))
            return out.strip()
        except Exception:
            return None


# ---------------------------------------------------------------- log helpers
def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Logger:
    """Writes steps (before row first, after row second), tool calls, rule results, decisions."""

    def __init__(self, con, run_id, case_id, model_tag, seed):
        self.con, self.run_id, self.case_id = con, run_id, case_id
        self.model_row = None
        if model_tag:
            self.model_row = f"{run_id}-m"
            con.execute("INSERT INTO models VALUES (?,?,?,?,?,?)",
                        (self.model_row, model_tag, "local", model_tag.split(":")[0], 0.0, seed))
            con.commit()

    def link(self, table, cur):
        log.link_row(self.con, table, cur.lastrowid)  # same transaction as the row

    def before(self, agent, seq, asked, uses_model):
        sid = f"{self.run_id}-{agent}-{seq}-b"
        cur = self.con.execute(
            "INSERT INTO steps (step_id, run_id, case_id, agent, phase, seq, model_row_id, prompt_sha256, asked,"
            " asked_sha256, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sid, self.run_id, self.case_id, agent, "before", seq, self.model_row if uses_model else None,
             log.sha256(asked) if uses_model else None, asked, log.sha256(asked), now()))
        self.link("steps", cur)
        self.con.commit()
        return sid

    def after(self, agent, seq, came_back, uses_model):
        sid = f"{self.run_id}-{agent}-{seq}-a"
        cur = self.con.execute(
            "INSERT INTO steps (step_id, run_id, case_id, agent, phase, seq, model_row_id, came_back,"
            " output_sha256, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, self.run_id, self.case_id, agent, "after", seq, self.model_row if uses_model else None,
             came_back, log.sha256(came_back), now()))
        self.link("steps", cur)
        self.con.commit()
        return sid

    def tool(self, step_id, tool, args, result):
        n = self.con.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
        cur = self.con.execute("INSERT INTO tool_calls VALUES (?,?,?,?,?,?)",
                               (f"{step_id}-t{n}", step_id, tool, json.dumps(args), json.dumps(result), now()))
        self.link("tool_calls", cur)
        self.con.commit()

    def rule_result(self, step_id, idx, rule_id, quote, passed, reason):
        cur = self.con.execute("INSERT INTO rule_results VALUES (?,?,?,?,?,?)",
                               (f"{step_id}-r{idx}", step_id, rule_id, quote, passed, reason))
        self.link("rule_results", cur)
        self.con.commit()

    def decision(self, step_id, idx, agent, decision, quote, rule_id, passed_to, model_wrote):
        cur = self.con.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
                               (f"{step_id}-d{idx}", step_id, agent, decision, quote, rule_id, passed_to, model_wrote))
        self.link("decisions", cur)
        self.con.commit()


# ---------------------------------------------------------------- prompts
def load_rules():
    data = json.loads(FRAMEWORK.read_text(encoding="utf-8"))
    return {c["rule_id"]: c["question"] for c in data["criteria"] if c.get("rule_id")}


def reader_prompt(ocr):
    return ("You are the reader. List the text below line by line, copied exactly, in order. "
            "No fixes, no comments. First line: PASS. If the text is empty or unreadable, write only UNKNOWN.\n"
            "--- TEXT ---\n" + ocr)


def checker_prompt(lines, rules, strict=False):
    rl = "\n".join(f"{k}: {v}" for k, v in sorted(rules.items()))
    return ("You are the rule checker. Suggest design faults in the text. Use rule ids from the list only. "
            "Reply with one JSON list and nothing else. Each item has these fields only: fault_id, rule_id, "
            "quote (copied from the text), location, severity, confidence, audience. Empty list if none.\n"
            + ("Your last reply was not valid. Reply with the JSON list only.\n" if strict else "")
            + "--- RULES ---\n" + rl + "\n--- TEXT ---\n" + "\n".join(lines))


def sendback_prompt(finding, reason, lines, rules):
    rl = "\n".join(f"{k}: {v}" for k, v in sorted(rules.items()))
    return ("You are the rule checker. The referee dropped one of your findings. "
            f"Referee reason: {reason}.\n"
            "Fix it or leave it out. Reply with one JSON list and nothing else: the same finding corrected "
            "(same fault_id; quote copied exactly from the text; rule id from the list), or an empty list.\n"
            "--- YOUR FINDING ---\n" + json.dumps(finding, sort_keys=True) +
            "\n--- RULES ---\n" + rl + "\n--- TEXT ---\n" + "\n".join(lines))


def send_back(lg, model, verdict, ocr, lines, rules, seed, seq, item_type=None):
    """Send one dropped finding back to the rule checker (the agent that made it). The reply goes
    through the referee again. Returns (new_verdict, failure). failure is None or a plain reason.
    A retry alone never confirms: the referee still needs a quote found in the text and a valid rule id."""
    f = verdict["finding"]
    asked = sendback_prompt(f, verdict["reason"], lines, rules)
    sid = lg.before("rule_checker", seq, asked, True)
    lg.tool(sid, "sendback", {"fault_id": f.get("fault_id"), "attempt": seq - 2, "max_retry": MAX_RETRY,
                              "reason": verdict["reason"]}, "sent back to rule_checker")
    try:
        out, hit = model.generate("rule_checker", asked, seed)
    except Exception as e:  # no 'after' row: log.failed_calls shows it
        return verdict, f"send-back call failed ({type(e).__name__})"
    lg.after("rule_checker", seq, out, True)
    reply = None if referee.repeat_detected(out, hit) else referee.strict_parse(out)
    if reply is None:
        lg.decision(sid, 0, "referee", "UNABLE TO CHECK", None, None, "sendback", "send-back reply not valid JSON")
        return verdict, "send-back reply could not be read"
    same = [r for r in reply if r.get("fault_id") == f.get("fault_id")]
    if not same:
        lg.decision(sid, 0, "referee", "drop", None, None, "sendback", "no corrected finding came back")
        return verdict, None
    new = referee.judge(same[:1], ocr, set(rules), item_type)[0]
    g = new["finding"]
    lg.decision(sid, 0, "referee", new["decision"], g.get("quote") if isinstance(g.get("quote"), str) else None,
                g.get("rule_id") if isinstance(g.get("rule_id"), str) else None, "sendback",
                json.dumps(g, sort_keys=True))
    return new, None


# ---------------------------------------------------------------- the run
def run_case(case, con, model, seed=0, heldout=False, host_note="orchestrator"):
    """Run one case. Returns dict(state, message, findings, dropped, reason, run_id).
    A crash in a model call leaves the 'before' row and no 'after' row (see log.failed_calls)."""
    case_id = case["case_id"]
    split = case.get("split", "dev")
    ocr = case.get("ocr_text", "") or ""
    tool_state = case.get("tool_state", "ok")
    if split == "heldout" and not heldout:
        raise CaseRefused("held-out case refused: give --heldout to open it")
    canon = json.dumps(case, sort_keys=True)
    if not con.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone():
        log.add_case(con, case_id, case.get("kind", "label"), split, log.sha256(canon),
                     case.get("planted", "none"), case.get("fault_types"))
    n = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] + 1
    run_id = f"run{n:04d}"
    if split == "heldout":
        if log.register_heldout_run(con, run_id, now(), DESIGN_VERSION, log.sha256(canon), seed) == "SPENT":
            raise CaseRefused("held-out already used for this design")
    else:
        con.execute("INSERT INTO runs VALUES (?,?,?,?,'dev','off',?,?)",
                    (run_id, now(), DESIGN_VERSION, log.sha256(canon), seed, host_note))
        con.commit()
    lg = Logger(con, run_id, case_id, getattr(model, "tag", None), seed)
    rules = load_rules()
    reason = None
    lines = []

    # ---- reader
    if tool_state != "ok":
        reason = f"tool state is {tool_state}"
    elif len(referee.fix_space(ocr)) < referee.MIN_TEXT:
        reason = "OCR text is empty or under 20 characters"
    if reason is None:
        asked = reader_prompt(ocr)
        sid = lg.before("reader", 1, asked, True)
        lg.tool(sid, "read_case", {"case_id": case_id}, {"chars": len(ocr)})
        out, hit = model.generate("reader", asked, seed)
        lg.after("reader", 1, out, True)
        first, _, rest = out.partition("\n")
        if first.strip() != "PASS" or hit:
            reason = "reader could not read the text"
        else:
            listed = [ln for ln in rest.split("\n") if ln.strip()]
            for i, ln in enumerate(listed):
                if not referee.quote_found(ln, ocr):
                    lg.decision(sid, i, "referee", "drop", ln, None, "reader_check",
                                "reader line not in OCR text")
            lines = [ln for ln in listed if referee.quote_found(ln, ocr)]
            if not lines:
                reason = "reader listed no usable line"

    # ---- rule checker (one retry)
    findings = None
    if reason is None:
        for seq in (1, 2):
            asked = checker_prompt(lines, rules, strict=(seq == 2))
            sid = lg.before("rule_checker", seq, asked, True)
            lg.tool(sid, "read_reader_output", {"lines": len(lines)}, "ok")
            lg.tool(sid, "read_rule_list", {"file": FRAMEWORK.name}, {"rules": len(rules)})
            out, hit = model.generate("rule_checker", asked, seed)
            lg.after("rule_checker", seq, out, True)
            if referee.repeat_detected(out, hit):
                why = "repeat detector fired"
            else:
                findings = referee.strict_parse(out)
                why = None if findings is not None else "output is not valid JSON"
            if why is None:
                break
            reason = why + (" on both tries" if seq == 2 else "")
        if findings is not None:
            reason = None

    # ---- send-back: each dropped finding goes back at most MAX_RETRY times; the referee judges again
    verdicts, sb_fail = [], None
    if reason is None:
        item_type = referee.classify_item(ocr, case.get("kind", "label"))
        verdicts = referee.judge(findings, ocr, set(rules), item_type)
        seq = 2
        for i, v in enumerate(list(verdicts)):
            sent = False
            for _ in range(MAX_RETRY):
                if v["decision"] != "drop" or sb_fail or v.get("retry") is False:
                    break
                seq += 1
                v, sb_fail = send_back(lg, model, v, ocr, lines, rules, seed, seq, item_type)
                sent = True
            verdicts[i] = dict(v, sent_back=True) if sent else v
        verdicts = referee.add_code_findings(verdicts, ocr, item_type, set(rules))

    # ---- referee (code, no model call)
    asked = json.dumps({"ocr_chars": len(ocr), "findings": findings}, sort_keys=True)
    sid = lg.before("referee", 1, asked, False)
    if reason is None:
        for i, (rid, fn) in enumerate(sorted(referee.REGEX_RULES.items())):
            hits = fn(ocr)
            lg.tool(sid, "regex_rule", {"rule_id": rid}, hits)
            lg.rule_result(sid, i, rid, hits[0] if hits else None, 0 if hits else 1,
                           "pattern found" if hits else "pattern not found")
        for f in findings:
            lg.tool(sid, "rule_id_lookup", {"rule_id": f.get("rule_id")}, f.get("rule_id") in rules)
        for i, v in enumerate(verdicts):
            f = v["finding"]
            lg.decision(sid, 100 + i, "referee", v["decision"], f.get("quote") if isinstance(f.get("quote"), str) else None,
                        f.get("rule_id") if isinstance(f.get("rule_id"), str) else None,
                        None, json.dumps(f, sort_keys=True))
    else:
        lg.decision(sid, 0, "referee", "UNABLE TO CHECK", None, None, None, reason)
    kept = [dict(rule_id=v["finding"]["rule_id"], quote=v["finding"]["quote"], state=v["decision"],
                 reason=v["reason"], **({"sent_back": True} if v.get("sent_back") else {}))
            for v in verdicts if v["decision"] != "drop"]
    dropped = [dict(rule_id=v["finding"].get("rule_id"), quote=v["finding"].get("quote"),
                    reason=v["reason"], **({"sent_back": True} if v.get("sent_back") else {}))
               for v in verdicts if v["decision"] == "drop"]
    if sb_fail:
        reason = sb_fail
        lg.decision(sid, 0, "referee", "UNABLE TO CHECK", None, None, None, reason)
    # ---- next check: fixed list by case type; the model may only pick from it
    kind = case.get("kind", "label")
    named = getattr(model, "name_next_check", lambda k, o: None)(kind, check_options(kind))
    next_check, refused = choose_next_check(kind, named)
    lg.tool(sid, "next_check", {"named": named, "allowed": check_options(kind)},
            {"used": next_check, "refused": refused})
    if reason is not None:
        state = "UNABLE TO CHECK"
        message = f"{UNABLE_TEXT}: {reason}. This is not a clean result."
    elif any(k["state"] == "DISPUTED" for k in kept):
        state = "DISPUTED"
        message = f"{len(kept)} fault(s) kept, at least one DISPUTED (a human must look). {len(dropped)} dropped."
    elif kept:
        state = "CONFIRMED"
        message = f"{len(kept)} fault(s) CONFIRMED by code. {len(dropped)} dropped."
    else:
        state = "CHECKED"
        message = f"Text was read. 0 faults passed the code check. {len(dropped)} dropped."
    lg.after("referee", 1, json.dumps(dict(state=state, findings=kept, dropped=dropped), sort_keys=True), False)
    return dict(state=state, message=message, findings=kept, dropped=dropped, reason=reason, run_id=run_id,
                next_check=next_check)


def final_list(result):
    return json.dumps([result["state"], result["findings"]], sort_keys=True)


def repeat_check(case, make_model, make_con, n=3, seed=0):
    """Run the same case n times at one seed. Return ('STABLE'|'UNSTABLE', results)."""
    results = []
    for _ in range(n):
        con = make_con()
        results.append(run_case(case, con, make_model(), seed))
        con.close()
    same = len({final_list(r) for r in results}) == 1
    return ("STABLE" if same else "UNSTABLE"), results


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Run one case through reader, rule checker and referee.")
    ap.add_argument("--case", required=True, help="case file (JSON: case_id, kind, split, tool_state, ocr_text)")
    ap.add_argument("--db", required=True, help="SQLite log file")
    ap.add_argument("--stub", action="store_true", help="fake local model (fixed outputs from files)")
    ap.add_argument("--stub-dir", help="folder with reader.txt and rule_checker.txt (default: <case>.stub)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--heldout", action="store_true", help="allow a held-out case (logged)")
    ap.add_argument("--repeat", type=int, default=0, help="run N times and report STABLE or UNSTABLE")
    a = ap.parse_args(argv)
    try:
        cpath = Path(a.case)
        case = json.loads(cpath.read_text(encoding="utf-8"))
        if "case_id" not in case:
            raise ValueError("case file has no case_id")
    except (OSError, ValueError) as e:
        print(f"{UNABLE_TEXT}: case file unreadable ({e}). This is not a clean result.")
        return 3
    if case.get("split") == "heldout" and not a.heldout:
        print("REFUSED: held-out case. Give --heldout to open it. No model was called.")
        return 2
    if a.stub:
        folder = Path(a.stub_dir) if a.stub_dir else cpath.with_suffix(".stub")
        make_model = lambda: StubModel(folder)  # noqa: E731
    else:
        make_model = LocalModel
    try:
        if a.repeat:
            verdict, results = repeat_check(case, make_model, lambda: log.open_db(a.db), a.repeat, a.seed)
            print(json.dumps(dict(repeat=verdict, runs=[final_list(r) for r in results]), indent=1))
            return 0 if verdict == "STABLE" else 4
        con = log.open_db(a.db)
        res = run_case(case, con, make_model(), a.seed, a.heldout)
        con.close()
    except CaseRefused as e:
        print(f"REFUSED: {e}")
        return 2
    except Exception as e:  # crash: the 'before' row is already in the log
        print(f"{UNABLE_TEXT}: run stopped ({type(e).__name__}: {e}). This is not a clean result.")
        return 3
    print(res["message"])
    print(json.dumps(dict(state=res["state"], findings=res["findings"], dropped=res["dropped"]), indent=1))
    return {"UNABLE TO CHECK": 3, "DISPUTED": 1}.get(res["state"], 0)


if __name__ == "__main__":
    sys.exit(main())
