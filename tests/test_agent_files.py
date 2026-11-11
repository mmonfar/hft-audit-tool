"""Tests for the agent role files (agents/) and case files (agent_tests/).

Written before the files (card hft-team-02). Files only: no model is run here.
Every check has a planted bad text in this file. The test shows the check
fails on it, so a check that cannot fail would be caught here.
Stdlib + pytest. A missing file makes the test FAIL (never skip).
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
TESTS = ROOT / "agent_tests"
CASES = TESTS / "cases"
FRAMEWORK = ROOT / "framework" / "hf_framework_v0.json"

NAMES = ["reader", "rule_checker", "referee"]
MODEL_ROLES = ["reader", "rule_checker"]
MODEL = "gpt-oss:20b"
PARTS = ["Job", "Inputs", "Tools", "Limits", "Stop rule", "Output", "Checked by"]
CONTRACT = ["fault_id", "rule_id", "quote", "location", "severity", "confidence", "audience"]
MODEL_TAG = re.compile(r"\b[a-z][\w.\-]*:\d+(?:\.\d+)?[bm]\b", re.I)
KINDS = {"planted", "clean", "unknown", "tool-fails"}


# ---------- checks (each returns a list of error strings) ----------

def check_parts(text):
    errs = []
    for p in PARTS:
        m = re.search(rf"^## {re.escape(p)}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if not m:
            errs.append(f"missing part: {p}")
        elif len(m.group(1).strip()) < 15:
            errs.append(f"part too thin: {p}")
    return errs


def check_models(text, is_model_role):
    errs = []
    tags = {t.lower() for t in MODEL_TAG.findall(text)}
    if is_model_role:
        if MODEL not in text:
            errs.append("model tag missing")
        if tags - {MODEL}:
            errs.append(f"other model tag: {sorted(tags - {MODEL})}")
    else:
        if "no model" not in text.lower():
            errs.append("must say 'no model'")
        if tags:
            errs.append(f"code role names a model tag: {sorted(tags)}")
        if "gpt-oss" in text.lower():
            errs.append("code role names gpt-oss")
    med = [ln for ln in text.splitlines() if "medgemma" in ln.lower()]
    if len(med) > 1:
        errs.append("MedGemma on more than one line")
    for ln in med:
        if ln.strip().lower() != "medgemma: not used":
            errs.append("MedGemma line must read exactly 'MedGemma: not used'")
    return errs


def check_output(text):
    m = re.search(r"^## Output\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    body = m.group(1) if m else ""
    errs = []
    for w in ("PASS", "FAIL", "UNKNOWN", "first line"):
        if w not in body:
            errs.append(f"Output lacks {w}")
    return errs


def check_rule_checker(text, root=ROOT):
    errs = []
    if "ids from the frozen list only" not in text:
        errs.append("missing phrase: ids from the frozen list only")
    for f in CONTRACT:
        if f not in text:
            errs.append(f"contract field missing: {f}")
    m = re.search(r"Frozen rule list: `([^`]+)`", text)
    if not m:
        errs.append("no pointer line 'Frozen rule list: `path`'")
    elif not (root / m.group(1)).is_file():
        errs.append(f"pointer path does not exist: {m.group(1)}")
    return errs


def check_referee(text):
    errs = []
    for w in ("CONFIRMED", "DISPUTED", "UNABLE TO CHECK", "last word", "white-space"):
        if w not in text:
            errs.append(f"referee file lacks {w}")
    return errs


def parse_cases(text):
    out = []
    for blk in re.split(r"^## Case ", text, flags=re.M)[1:]:
        head, _, body = blk.partition("\n")
        c = {"id": head.strip()}
        for key in ("kind", "input", "expected", "could fail if"):
            m = re.search(rf"^- {re.escape(key)}: (.+)$", body, re.M)
            c[key] = m.group(1).strip() if m else ""
        out.append(c)
    return out


def check_cases(text, agent_dir, rule_ids=None):
    errs = []
    cases = parse_cases(text)
    kinds = [c["kind"] for c in cases]
    if len(cases) < 5:
        errs.append(f"only {len(cases)} cases")
    if kinds.count("planted") < 3:
        errs.append("fewer than 3 planted cases")
    for k in ("clean", "unknown", "tool-fails"):
        if k not in kinds:
            errs.append(f"no {k} case")
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        errs.append("duplicate case id")
    for c in cases:
        if c["kind"] not in KINDS:
            errs.append(f"{c['id']}: bad kind {c['kind']!r}")
        if not c["expected"]:
            errs.append(f"{c['id']}: no expected answer")
        if not c["could fail if"]:
            errs.append(f"{c['id']}: no note on how it could fail")
        if not c["input"] or not (CASES / agent_dir / c["input"]).is_file():
            errs.append(f"{c['id']}: input file missing: {c['input']!r}")
        if c["kind"] == "unknown" and not c["expected"].startswith("UNKNOWN"):
            errs.append(f"{c['id']}: unknown case must expect UNKNOWN")
        if c["kind"] == "tool-fails" and not c["expected"].startswith("UNKNOWN"):
            errs.append(f"{c['id']}: tool-fails case must expect UNKNOWN")
        if c["kind"] == "clean" and not c["expected"].startswith("PASS"):
            errs.append(f"{c['id']}: clean case must expect PASS")
        if rule_ids is not None:
            for rid in re.findall(r"\b[A-Z]{3,4}-\d\d\b", c["expected"]):
                if rid not in rule_ids:
                    errs.append(f"{c['id']}: rule id not in frozen list: {rid}")
    for need in ("Runs per case: 3", "Model: " + MODEL, "written before any run"):
        if need not in text:
            errs.append(f"missing line: {need}")
    errs += check_models(text, True)
    return errs


def frozen_ids():
    data = json.loads(FRAMEWORK.read_text(encoding="utf-8"))
    return {c["rule_id"] for c in data["criteria"] if c["rule_id"]}


def read(p):
    assert p.is_file(), f"file missing: {p}"
    return p.read_text(encoding="utf-8")


# ---------- good files ----------

@pytest.mark.parametrize("name", NAMES)
def test_role_has_seven_parts(name):
    assert check_parts(read(AGENTS / f"{name}.md")) == []


@pytest.mark.parametrize("name", NAMES)
def test_role_models(name):
    assert check_models(read(AGENTS / f"{name}.md"), name in MODEL_ROLES) == []


@pytest.mark.parametrize("name", NAMES)
def test_role_output(name):
    assert check_output(read(AGENTS / f"{name}.md")) == []


def test_rule_checker_specific():
    assert check_rule_checker(read(AGENTS / "rule_checker.md")) == []


def test_referee_specific():
    assert check_referee(read(AGENTS / "referee.md")) == []


@pytest.mark.parametrize("name", NAMES)
def test_case_file(name):
    assert check_cases(read(TESTS / f"{name}.md"), name, frozen_ids() if name == "rule_checker" else None) == []


def test_every_case_input_is_listed():
    for name in NAMES:
        listed = {c["input"] for c in parse_cases(read(TESTS / f"{name}.md"))}
        on_disk = {p.name for p in (CASES / name).iterdir() if p.is_file()}
        assert on_disk == listed, f"{name}: files and case list differ"


def test_rule_checker_cases_use_frozen_ids():
    ids = set()
    for c in parse_cases(read(TESTS / "rule_checker.md")):
        ids |= set(re.findall(r"\b[A-Z]{3,4}-\d\d\b", c["expected"]))
    assert ids and ids <= frozen_ids()


# ---------- planted bad texts: each check must fail ----------

GOOD_ROLE = "".join(f"## {p}\nSome text for this part, long enough.\n\n" for p in PARTS)


def test_plant_part_missing():
    bad = GOOD_ROLE.replace("## Stop rule", "## Halt")
    assert any("Stop rule" in e for e in check_parts(bad))
    assert check_parts(GOOD_ROLE) == []


def test_plant_part_empty():
    bad = GOOD_ROLE.replace("## Limits\nSome text for this part, long enough.", "## Limits\nx")
    assert any("Limits" in e for e in check_parts(bad))


def test_plant_other_model_and_medgemma():
    assert check_models(f"Model {MODEL}", True) == []
    assert check_models(f"Model {MODEL} and llama3:8b", True)
    assert check_models(f"Model {MODEL}\nMedGemma: not used", True) == []
    assert check_models(f"Model {MODEL}\nWe use MedGemma here", True)
    assert check_models(f"Model {MODEL}\nMedGemma: not used\nMedGemma: not used", True)
    assert check_models("Model other", True)


def test_plant_referee_with_model():
    assert check_models("This role uses no model.", False) == []
    assert check_models("This role uses no model. Tag gpt-oss:20b", False)
    assert check_models("Runs on a model.", False)


def test_plant_output_without_unknown():
    good = "## Output\nFirst line is PASS, FAIL or UNKNOWN. The first line only.\n"
    assert check_output(good) == []
    assert check_output(good.replace("UNKNOWN", "MAYBE"))


def test_plant_rule_checker(tmp_path):
    (tmp_path / "f.json").write_text("{}", encoding="utf-8")
    good = ("ids from the frozen list only " + " ".join(CONTRACT)
            + "\nFrozen rule list: `f.json`\n")
    assert check_rule_checker(good, tmp_path) == []
    assert check_rule_checker(good.replace("ids from the frozen list only", "any id"), tmp_path)
    assert check_rule_checker(good.replace("f.json", "nope.json"), tmp_path)
    assert check_rule_checker(good.replace("quote", "q"), tmp_path)


def test_plant_referee_words():
    good = "CONFIRMED DISPUTED UNABLE TO CHECK last word white-space"
    assert check_referee(good) == []
    assert check_referee(good.replace("DISPUTED", ""))


def _case(i, kind, expected="PASS", inp="a.txt", fail="x"):
    return (f"## Case {i}\n- kind: {kind}\n- input: {inp}\n- expected: {expected}\n"
            f"- could fail if: {fail}\n\n")


GOOD_CASES = (_case("1", "planted", "FAIL EMR-01") + _case("2", "planted", "FAIL EMR-01")
              + _case("3", "planted", "FAIL EMR-01") + _case("4", "clean", "PASS")
              + _case("5", "unknown", "UNKNOWN") + _case("6", "tool-fails", "UNKNOWN"))
HEAD = f"Model: {MODEL}\nRuns per case: 3\nCorrect answers are written before any run.\n\n"
HEAD = HEAD.replace("are written before any run", "written before any run")


@pytest.fixture
def cdir(tmp_path, monkeypatch):
    d = tmp_path / "ag"
    d.mkdir()
    (d / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setitem(globals(), "CASES", tmp_path)
    return "ag"


def test_plant_cases_baseline_passes(cdir):
    assert check_cases(HEAD + GOOD_CASES, cdir) == []


def test_plant_four_cases(cdir):
    bad = HEAD + GOOD_CASES.replace(_case("6", "tool-fails", "UNKNOWN"), "")
    assert check_cases(bad, cdir)


def test_plant_missing_kinds(cdir):
    for kind in ("clean", "unknown", "tool-fails"):
        exp = {"clean": "PASS", "unknown": "UNKNOWN", "tool-fails": "UNKNOWN"}[kind]
        bad = HEAD + GOOD_CASES.replace(_case({"clean": "4", "unknown": "5", "tool-fails": "6"}[kind], kind, exp),
                                        _case("9", "planted", "FAIL EMR-01"))
        assert any(kind in e for e in check_cases(bad, cdir)), kind


def test_plant_no_expected(cdir):
    bad = HEAD + GOOD_CASES.replace("- expected: FAIL EMR-01\n", "- expected: \n", 1)
    assert any("no expected" in e for e in check_cases(bad, cdir))


def test_plant_no_failure_note(cdir):
    bad = HEAD + GOOD_CASES.replace("- could fail if: x\n", "- could fail if: \n", 1)
    assert any("how it could fail" in e for e in check_cases(bad, cdir))


def test_plant_missing_input_file(cdir):
    bad = HEAD + GOOD_CASES.replace("a.txt", "gone.txt", 1)
    assert any("input file missing" in e for e in check_cases(bad, cdir))


def test_plant_wrong_unknown_answer(cdir):
    bad = HEAD + GOOD_CASES.replace(_case("5", "unknown", "UNKNOWN"), _case("5", "unknown", "PASS"))
    assert any("must expect UNKNOWN" in e for e in check_cases(bad, cdir))


def test_plant_invented_rule_id(cdir):
    bad = HEAD + GOOD_CASES.replace("FAIL EMR-01", "FAIL ZZZ-99", 1)
    assert any("not in frozen list" in e for e in check_cases(bad, cdir, {"EMR-01"}))


def test_plant_header_lines_missing(cdir):
    bad = (HEAD + GOOD_CASES).replace("Runs per case: 3", "Runs per case: 2")
    assert any("Runs per case" in e for e in check_cases(bad, cdir))
    bad = (HEAD + GOOD_CASES).replace("written before any run", "")
    assert any("written before" in e for e in check_cases(bad, cdir))
