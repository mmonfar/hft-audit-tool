"""Keyword retrieval over the 24 framework criteria. Context only, never proof.
Expected ids were written before the first run. Plain keyword, standard library only."""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

import referee
import retrieve

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "framework" / "hf_framework_v0.json"
STORED = {c["id"]: c for c in json.loads(FILE.read_text(encoding="utf-8"))["criteria"]}
NEEDS = "needs source"

# (query, expected first-hit criterion id, expected rule id or None)
HITS = [
    ("alert told apart from other alerts on the same screen", "alert-02", "ALT-02"),
    ("look-alike drug names tall-man letters", "order_set-02", "EMR-02"),
    ("buttons at least 24 px in the alert", "alert-09", "EMR-03"),
    ("misread abbreviations in the note", "note-04", "EMR-01"),
]
# hits on items whose stored source is "needs source"
NEEDS_HITS = [
    ("open tasks ranked by risk or by time", "note-03", "NOTE-03"),
    ("pre-ticked items safe default", "order_set-05", None),
]
NONSENSE = ["zxqv blorp wibble", "quantum banana submarine", "the of and", ""]
# EXPECTED MISS: right meaning, different words. Keyword search cannot find it.
EXPECTED_MISS = ("notification clarity", "alert-01")


@pytest.mark.parametrize("q,cid,rid", HITS + NEEDS_HITS)
def test_expected_first_hit(q, cid, rid):
    hits = retrieve.search(q)
    assert hits, q
    assert hits[0]["id"] == cid
    assert hits[0]["rule_id"] == rid


@pytest.mark.parametrize("q", NONSENSE)
def test_no_match_returns_nothing(q):
    assert retrieve.search(q) == []
    out = retrieve.render(q, [])
    assert "no match" in out
    assert "source:" not in out
    for c in STORED.values():
        if c["source"] != NEEDS:
            assert c["source"] not in out


def test_expected_miss_is_a_miss():
    q, cid = EXPECTED_MISS
    assert cid not in [h["id"] for h in retrieve.search(q)]
    assert retrieve.search(q) == []  # keyword fails here; shown, not hidden


def test_source_copied_exactly_for_all_24():
    assert len(STORED) == 24
    seen = set()
    for cid, c in STORED.items():
        for h in retrieve.search(c["question"], limit=24):
            if h["id"] == cid:
                seen.add(cid)
                assert h["source"] == c["source"]
                assert h["question"] == c["question"]
    assert seen == set(STORED), set(STORED) - seen


def test_needs_source_labelled_count_from_file():
    n = sum(1 for c in STORED.values() if c["source"] == NEEDS)
    assert n > 0
    got = [h for c in STORED.values() for h in retrieve.search(c["question"], limit=24)
           if h["id"] == c["id"] and h["source"] == NEEDS]
    assert len(got) == n
    assert all(h["sourced"] is False for h in got)
    q = "open tasks ranked by risk"
    text = retrieve.render(q, retrieve.search(q))
    assert "needs source" in text and "not sourced" in text


def test_missing_source_field_is_needs_source(tmp_path):
    d = json.loads(FILE.read_text(encoding="utf-8"))
    del d["criteria"][0]["source"]
    p = tmp_path / "f.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    hits = retrieve.search("alert name the value or the reason", path=p)
    assert hits[0]["id"] == "alert-01"
    assert hits[0]["source"] == NEEDS and hits[0]["sourced"] is False


def test_planted_source_edit_is_caught(tmp_path):
    d = json.loads(FILE.read_text(encoding="utf-8"))
    d["criteria"][1]["source"] = "invented-source"
    p = tmp_path / "f.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    h = retrieve.search(d["criteria"][1]["question"], path=p)[0]
    assert h["source"] != STORED["alert-02"]["source"]  # the all-24 check fails on such an edit


def test_stable_order_and_cap():
    a = retrieve.search("alert", limit=5)
    assert a == retrieve.search("alert", limit=5)
    assert len(a) <= 5
    scores = [h["score"] for h in a]
    assert scores == sorted(scores, reverse=True)


def test_heading_is_context_not_proof():
    out = retrieve.render("alert", retrieve.search("alert"))
    assert out.startswith("Context (not proof)")


def test_retrieved_text_alone_is_dropped_by_referee():
    h = retrieve.search("alert told apart from other alerts on the same screen")[0]
    finding = {"fault_id": "F1", "rule_id": h["rule_id"], "quote": h["question"] + " " + h["failure_mode"],
               "location": "x", "severity": "major", "confidence": 0.9, "audience": "nurse"}
    ocr = "Heparin 5000 units. Press OK to continue and close this window now."
    v = referee.judge([finding], ocr, {"ALT-02"})
    assert v[0]["decision"] == "drop"


def test_no_vector_imports_and_stdlib_only():
    tree = ast.parse((ROOT / "retrieve.py").read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
    assert not (mods & {"numpy", "sklearn", "chromadb", "chroma", "faiss", "socket", "urllib", "http", "requests"})


def test_only_reads_inside_repo():
    src = (ROOT / "retrieve.py").read_text(encoding="utf-8")
    assert ".env" not in src
    assert retrieve.DEFAULT_FILE.resolve().is_relative_to(ROOT.resolve())


def test_command_line_prints_rule_question_source():
    r = subprocess.run([sys.executable, str(ROOT / "retrieve.py"), "buttons at least 24 px"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0
    assert "Context (not proof)" in r.stdout and "EMR-03" in r.stdout and "wcag-22-reference" in r.stdout
    r = subprocess.run([sys.executable, str(ROOT / "retrieve.py"), "zxqv blorp"],
                       capture_output=True, text=True, cwd=ROOT)
    assert "no match" in r.stdout
