"""Helpers for the orchestrator tests (cases, stub files). Synthetic data only. Standard library only."""
import json
from pathlib import Path


OCR = "ALERT\nOrder: Zorvatin 5 mg tablet QD\nPatient: Test Patient 01\nOK"
GOOD_FINDING = {"fault_id": "f1", "rule_id": "EMR-01", "quote": "Zorvatin 5 mg tablet QD", "location": "line 2",
                "severity": "major", "confidence": 0.8, "audience": "nurse"}


def make_case(case_id="T1", ocr=OCR, split="dev", tool_state="ok", planted="none"):
    return {"case_id": case_id, "kind": "alert", "split": split, "tool_state": tool_state,
            "ocr_text": ocr, "planted": planted}


def write_stub(folder, reader=None, checker=None, extra=None):
    """Write stub model outputs. reader/checker are the text of reader.txt / rule_checker.txt.
    extra: {file name: text} for per-try files such as rule_checker.2.txt."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if reader is None:
        reader = "PASS\n" + OCR
    if checker is None:
        checker = json.dumps([GOOD_FINDING])
    (folder / "reader.txt").write_text(reader, encoding="utf-8")
    (folder / "rule_checker.txt").write_text(checker, encoding="utf-8")
    for name, text in (extra or {}).items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def rows(con, sql, *args):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


CODE_ONLY = "found by code rule, no model finding"


def model_only(res):
    """Findings the model made. Findings the referee added from its own code rules are left out."""
    return [f for f in res["findings"] if f.get("reason") != CODE_ONLY]
