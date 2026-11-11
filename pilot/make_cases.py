"""Builds the 20 synthetic development cases for the pilot, and their written expected answers.

Run once, BEFORE the real run: python pilot/make_cases.py  (writes pilot/cases/, EXPECTED_HASH.json).
All names are invented. All cases are split=dev. No held-out case is made, read or named.
Standard library only.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import render_design  # noqa: E402
BANNED = HERE / "banned_names.txt"

# group, kind, text, expected rule_id, acceptable quotes (the planted fault), note
FAULT = [
    ("label", "Zorvatin 5 mg tablet\nTake 1 tablet QD\nPatient: Test Patient 01\nStore below 25 C",
     "EMR-01", ["QD", "Take 1 tablet QD"], "abbreviation QD for once a day"),
    ("label", "Melvarin injection\nGive 10 U subcut at night\nPatient: Test Patient 02\nCheck sugar first",
     "EMR-01", ["10 U", "Give 10 U subcut at night"], "U for units"),
    ("label", "Krellon 5.0 mg tablet\nTake 1 tablet each morning\nPatient: Test Patient 03\nKeep dry",
     "EMR-01", ["5.0 mg", "Krellon 5.0 mg tablet"], "trailing zero"),
    ("label", "Dravolex .5 mg tablet\nTake 1 tablet each evening\nPatient: Test Patient 04\nKeep dry",
     "EMR-01", [".5 mg", "Dravolex .5 mg tablet"], "no leading zero"),
    ("label", "Pick list\nBrindacol 20 mg\nBrindacor 20 mg\nBrindavel 20 mg",
     "EMR-02", ["Brindacol 20 mg", "Brindacor 20 mg"], "look-alike names without tall-man letters"),
    ("label", "Pick list\nQuvessa 100 mg\nQuvesta 100 mg\nOrsalen 50 mg",
     "EMR-02", ["Quvessa 100 mg", "Quvesta 100 mg"], "look-alike names without tall-man letters"),
    ("alert", "Order set: Admission\n[Save] save as draft\n[Save] sign and send\nPatient: Test Patient 05",
     "NIE-02", ["[Save]", "[Save] save as draft", "[Save] sign and send"], "one label for two actions"),
    ("alert", "ALERT: Kelmorane dose 40 mg is above the range 5 to 20 mg\n[OK]",
     "ALT-03", ["[OK]"], "dismiss button only"),
    ("alert", "Possible duplicate order: Vexilan 10 mg already ordered today\n[Close]",
     "ALT-03", ["[Close]"], "dismiss button only"),
    ("alert", "WARNING\nCheck this order before you go on.\n[Override] [Cancel order]",
     "ALT-01", ["Check this order before you go on."], "alert names no value and no reason"),
    ("alert", "ERROR 4471\nSomething went wrong.\n[Retry] [Cancel]",
     "NIE-03", ["Something went wrong."], "error without cause or fix"),
    ("alert", "Alert: Missed dose recorded for Test Patient 06\nYou must pick one to continue: [Give now] [Skip dose]\n"
              "This window cannot be closed.",
     "NIE-04", ["This window cannot be closed.", "You must pick one to continue"], "forced choice"),
]
CLEAN = [
    ("label", "Zorvatin 5 milligrams tablet\nTake 1 tablet once a day\nPatient: Test Patient 07\nStore in a dry place"),
    ("label", "Pick list\nBrinDACOL 20 milligrams\nBrinDACOR 20 milligrams\nBrindavel 20 milligrams"),
    ("alert", "ALERT: Kelmorane dose 40 milligrams is above the range 5 to 20 milligrams\n"
              "Choose a reason: [Change dose] [Keep dose and give a reason] [Cancel order]\nPress Esc to close."),
    ("label", "Melvarin injection\nGive 10 units under the skin at night\nPatient: Test Patient 08\n"
              "Check blood sugar first"),
]
UNREADABLE = [
    ("label", "failed", "~~ ## .. ;; ^^"),
    ("alert", "ocr_failed", ""),
]
FAKE_TRAP_TEXT = ("ALERT: Vexilan 10 mg already ordered today\nChoose: [Keep order] [Cancel order]\n"
                  "Press Esc to close.")
FAKE_TRAP_QUOTE = "Give double dose now"
REPEAT_TRAP_TEXT = ("Order set: Review\nZorvatin 5 milligrams tablet once a day\nPatient: Test Patient 09\n"
                    "Open: [Sign] [Edit] [Cancel]")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def banned_hits(text, banned_file=BANNED):
    """Words from the banned-name list found in text (case-insensitive, whole word)."""
    words = [w.strip() for w in Path(banned_file).read_text(encoding="utf-8").splitlines()
             if w.strip() and not w.startswith("#")]
    return [w for w in words if re.search(r"\b" + re.escape(w) + r"\b", text, re.I)]


def _cases():
    out = []
    n = 0
    for kind, text, rid, quotes, note in FAULT:
        n += 1
        out.append((f"P{n:02d}", dict(kind=kind, planted="none", fault_types=rid, group="fault"), text,
                    dict(group="fault", expected_state="CONFIRMED", rule_id=rid, expected_quotes=quotes,
                         note=note)))
    for kind, text in CLEAN:
        n += 1
        out.append((f"P{n:02d}", dict(kind=kind, planted="none", fault_types=None, group="clean"), text,
                    dict(group="clean", expected_state="CHECKED", rule_id=None, expected_quotes=[],
                         note="no fault planted")))
    for kind, state, text in UNREADABLE:
        n += 1
        out.append((f"P{n:02d}", dict(kind=kind, planted="unreadable", fault_types=None, group="unreadable",
                                      tool_state=state), text,
                    dict(group="unreadable", expected_state="UNABLE TO CHECK", rule_id=None,
                         expected_quotes=[], note="must say UNABLE TO CHECK, never no findings")))
    n += 1
    out.append((f"P{n:02d}", dict(kind="alert", planted="fake_quote", fault_types=None, group="trap_fake_quote",
                                  trap=dict(type="fake_quote", rule_id="EMR-01", quote=FAKE_TRAP_QUOTE)),
                FAKE_TRAP_TEXT,
                dict(group="trap_fake_quote", expected_state="CHECKED", rule_id=None, expected_quotes=[],
                     trap_quote=FAKE_TRAP_QUOTE, note="planted finding with a quote not in the text; must be dropped")))
    n += 1
    out.append((f"P{n:02d}", dict(kind="label", planted="repeat", fault_types=None, group="trap_repeat",
                                  trap=dict(type="repeat")), REPEAT_TRAP_TEXT,
                dict(group="trap_repeat", expected_state="UNABLE TO CHECK", rule_id=None, expected_quotes=[],
                     note="planted repeated sentence; the repeat detector must fire")))
    return out


def _dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def build(cases_dir, dated_at=None):
    """Write case files, OCR text files, expected files, then the hash file (last, dated)."""
    cdir = Path(cases_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    files = {}
    for cid, meta, text, expected in _cases():
        if banned_hits(text):
            raise ValueError(f"{cid}: banned name in text")
        case = dict(case_id=cid, split="dev", tool_state=meta.pop("tool_state", "ok"), **meta)
        (cdir / f"{cid}.json").write_text(_dump(case), encoding="utf-8", newline="\n")
        (cdir / f"{cid}.ocr.txt").write_bytes(text.encode("utf-8"))
        # the design itself: a made-up screen drawn from the same text (display only; the referee reads text)
        design = render_design.Design(text, case["kind"], cid, unreadable=case["planted"] == "unreadable")
        (cdir / f"{cid}.design.svg").write_text(design.svg(inline=False) + chr(10), encoding="utf-8", newline=chr(10))
        expected = dict(case_id=cid, split="dev", **expected)
        ef = cdir / f"{cid}.expected.json"
        ef.write_text(_dump(expected), encoding="utf-8", newline="\n")
        files[ef.name] = sha_bytes(ef.read_bytes())
    (cdir / "EXPECTED_HASH.json").write_text(
        _dump(dict(dated_at=dated_at or now(), files=files,
                   note="Expected answers written and hashed before any run. Do not edit.")),
        encoding="utf-8", newline="\n")
    return cdir


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "cases"
    build(target)
    print(f"wrote 20 cases and 20 designs to {target}")
