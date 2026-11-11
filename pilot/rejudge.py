"""Re-judge the 20 stored pilot outputs with the current referee. No model call.

python pilot/rejudge.py [--out pilot/rejudge_result.json]

Reads the saved reader and rule checker outputs from pilot/pilot_run.sqlite and replays them,
in the saved order, through orchestrator.run_case. A replay that asks for an output that was
never saved (a send-back the old run did not make) stops that case: it is counted as
"replay_gap" and shown, never guessed. Counts only (x of n). No percent, no accuracy.
Standard library only. Development cases only.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import log  # noqa: E402
import orchestrator  # noqa: E402
import run_pilot  # noqa: E402

LABEL = "PILOT, 20 made-up development cases, re-judged by code, same model outputs"


class ReplayGap(Exception):
    pass


class ReplayModel:
    """Hands back the saved model outputs, in the saved order. Never calls a model."""
    tag = "stub"

    def __init__(self, saved):
        self.saved = {k: list(v) for k, v in saved.items()}

    def generate(self, agent, prompt, seed=0):
        if not self.saved.get(agent):
            raise ReplayGap(f"no saved {agent} output for this call")
        return self.saved[agent].pop(0), False

    def name_next_check(self, kind, options):
        return None


def saved_outputs(db_path):
    """case_id -> {agent: [saved answers in order]} for the two model agents."""
    con = sqlite3.connect(str(db_path))
    out = {}
    for case_id, agent, came in con.execute(
            "SELECT case_id, agent, came_back FROM steps WHERE phase='after' AND agent IN ('reader','rule_checker')"
            " ORDER BY rowid"):
        out.setdefault(case_id, {}).setdefault(agent, []).append(came or "")
    con.close()
    return out


def rejudge(cases_dir, db_path, work_dir):
    cases = run_pilot.load_cases(cases_dir)
    saved = saved_outputs(db_path)
    per = []
    con = log.open_db(str(Path(work_dir) / "rejudge.sqlite"))
    for c in cases:
        run_input = {k: v for k, v in c.items() if k not in ("expected", "expected_sha256", "group", "trap")}
        try:
            res = orchestrator.run_case(run_input, con, ReplayModel(saved.get(c["case_id"], {})),
                                        host_note="rejudge, no model call")
            final = dict(state=res["state"], findings=res["findings"], dropped=res["dropped"],
                         reason=res["reason"], message=res["message"])
            sc = run_pilot.score_case(c["expected"], final)
            per.append(dict(case_id=c["case_id"], group=c["group"], expected=c["expected"], final=final,
                            outcome=sc["outcome"], extra_kept=sc["extra_kept"]))
        except ReplayGap as e:
            per.append(dict(case_id=c["case_id"], group=c["group"], expected=c["expected"],
                            final=dict(state="REPLAY GAP", findings=[], dropped=[], reason=str(e), message=str(e)),
                            outcome="replay_gap", extra_kept=0))
    con.close()
    return per


def build(cases_dir=HERE / "cases", db_path=HERE / "pilot_run.sqlite", before_path=HERE / "pilot_result.json"):
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        per = rejudge(cases_dir, db_path, td)
    after = run_pilot.tally(per)
    after["replay_gap"] = dict(value=f"{sum(c['outcome'] == 'replay_gap' for c in per)} of 20", label=LABEL)
    for k in after:
        after[k]["label"] = LABEL
    return dict(label=LABEL, note="Pre-check only. Does not replace a human factors engineer. Not a medical device. "
                                  "NOT REVIEWED. Counts only. No model call was made.",
                before={k: dict(value=v["value"], label=run_pilot.PILOT_LABEL) for k, v in before["counts"].items()},
                after=after,
                changes=[dict(case_id=p["case_id"], before=b["outcome"], after=p["outcome"],
                              before_extra_kept=b["extra_kept"], after_extra_kept=p["extra_kept"])
                         for p, b in zip(per, before["per_case"]) if (p["outcome"], p["extra_kept"]) !=
                         (b["outcome"], b["extra_kept"])],
                per_case=per)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-judge stored pilot outputs. No model call.")
    ap.add_argument("--out", default=str(HERE / "rejudge_result.json"))
    a = ap.parse_args(argv)
    res = build()
    run_pilot.write_json(a.out, res)
    for k in ("found", "missed", "false_alarms", "unable_to_check", "traps_caught", "replay_gap"):
        b = res["before"].get(k, {}).get("value", "-")
        print(f"{k}: before {b}, after {res['after'][k]['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
