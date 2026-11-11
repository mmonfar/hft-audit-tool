"""Risk step tests (hft-team-07). Synthetic data only. Each rule has a planted break that must fail."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "framework"))
import framework as fw  # noqa: E402

import risk_step as rs  # noqa: E402

DISC = "Pre-check. Not a medical device. Does not replace a human factors engineer. NOT REVIEWED."
EX = "example, not measured"
MODEL_REASON = "model and regex rule disagree"


def verdict(fid, rule, decision="CONFIRMED", reason="quote found, rule id valid, regex agrees", model_sev=None):
    f = {"fault_id": fid, "rule_id": rule, "quote": "q " + fid}
    if model_sev is not None:
        f["severity"] = model_sev
    return {"finding": f, "decision": decision, "reason": reason}


TABLE = {"R-HI": ("critical", "src-a"), "R-MID": ("major", "needs source"), "R-LO": ("minor", "src-b")}


def ids(ranked):
    return [r["fault_id"] for r in ranked]


# ---- severity source
def test_severity_comes_from_table_with_source():
    a = rs.assess(verdict("f1", "R-HI"), table=TABLE)
    assert a["severity"]["value"] == "critical" and a["severity"]["source"] == "src-a"


def test_unknown_rule_is_not_set_and_ranks_last():
    out = rs.rank([rs.assess(verdict("u", "R-NONE"), table=TABLE),
                   rs.assess(verdict("m", "R-LO"), table=TABLE)])
    assert ids(out) == ["m", "u"]
    assert out[1]["severity"]["value"] is None
    assert out[1]["severity"]["label"] == "severity: not set"


def test_model_severity_is_proposal_and_ranks_nothing():
    a = rs.assess(verdict("p", "R-NONE", model_sev=10), table=TABLE)
    assert a["severity"]["value"] is None
    assert a["severity_proposal"]["label"] == "PROPOSAL (model), not a score"
    assert a["severity_proposal"]["value"] == 10
    b = rs.assess(verdict("q", "R-LO"), table=TABLE)
    assert ids(rs.rank([a, b])) == ["q", "p"]
    assert "PROPOSAL (model), not a score" in rs.render(rs.rank([a, b]))


def test_model_proposal_never_overrides_table():
    a = rs.assess(verdict("p", "R-LO", model_sev=10), table=TABLE)
    assert a["severity"]["value"] == "minor"


def test_human_row_sets_severity_and_ranks():
    v = verdict("p", "R-NONE", model_sev=10)
    a = rs.assess(v, table=TABLE, human_rows=[{"fault_id": "p", "severity": "critical", "by": "human"}])
    assert a["severity"]["value"] == "critical" and a["severity"]["source"] == "human entry"
    b = rs.assess(verdict("q", "R-MID"), table=TABLE)
    assert ids(rs.rank([b, a])) == ["p", "q"]


def test_bad_human_row_refused():
    with pytest.raises(ValueError):
        rs.assess(verdict("p", "R-LO"), table=TABLE, human_rows=[{"fault_id": "p", "severity": 10}])


def test_real_table_every_row_has_source_or_needs_source():
    assert rs.SEVERITY_TABLE
    for rule, (level, src) in rs.SEVERITY_TABLE.items():
        assert level in rs.SEVERITY_LEVELS
        assert isinstance(src, str) and src.strip()


# ---- no product number
def test_no_product_and_no_rpn_key():
    a = rs.assess(verdict("f1", "R-HI"), table=TABLE)
    assert set(a) >= {"severity", "occurrence", "detection"}
    assert rs.forbidden_keys(a) == []
    assert not re.search(r"\brpn\b", rs.render(rs.rank([a])), re.I)


def test_code_has_no_product_or_rpn_word():
    src = (ROOT / "risk_step.py").read_text(encoding="utf-8")
    assert not re.search(r"\brpn\b", src, re.I)
    assert not re.search(r"\w+\s*\*\s*\w+\s*\*\s*\w+", src)


def test_planted_rpn_key_is_caught():
    a = rs.assess(verdict("f1", "R-HI"), table=TABLE)
    a["rpn"] = 200
    assert rs.forbidden_keys(a) == ["rpn"]


# ---- occurrence
def test_invented_case_occurrence_exact_text():
    for r in ("R-HI", "R-MID", "R-NONE"):
        assert rs.assess(verdict("x", r), table=TABLE)["occurrence"]["text"] == EX


def test_real_count_needs_n():
    v = verdict("x", "R-HI")
    with pytest.raises(ValueError):
        rs.assess(v, table=TABLE, real_counts={"R-HI": {"k": 3}})
    a = rs.assess(v, table=TABLE, real_counts={"R-HI": {"k": 3, "n": 40}})
    assert "n=40" in a["occurrence"]["text"] and a["occurrence"]["text"] != EX


# ---- detection
def test_detection_labels():
    code = rs.assess(verdict("a", "R-HI"), table=TABLE)["detection"]["text"]
    quote = rs.assess(verdict("b", "R-HI", reason="quote found, rule id valid"), table=TABLE)["detection"]["text"]
    model = rs.assess(verdict("c", "R-HI", "DISPUTED", MODEL_REASON), table=TABLE)["detection"]["text"]
    assert (code, quote, model) == ("code rule", "quote match", "model only")


# ---- ranking
def test_rank_severity_first_even_when_a_product_would_say_otherwise():
    hi = rs.assess(verdict("hi", "R-HI"), table=TABLE)
    lo = rs.assess(verdict("lo", "R-LO", "DISPUTED", MODEL_REASON), table=TABLE)
    assert rs.product_proxy(lo) > rs.product_proxy(hi)  # a product ranker would put lo first
    assert ids(rs.rank([lo, hi])) == ["hi", "lo"]


def test_product_ranker_would_fail_the_ranking_test():
    hi = rs.assess(verdict("hi", "R-HI"), table=TABLE)
    lo = rs.assess(verdict("lo", "R-LO", "DISPUTED", MODEL_REASON), table=TABLE)
    bad = sorted([hi, lo], key=lambda a: -rs.product_proxy(a))
    assert ids(bad) != ["hi", "lo"]


def test_rank_then_weak_detection_then_input_order():
    code = rs.assess(verdict("code", "R-LO"), table=TABLE)
    model = rs.assess(verdict("model", "R-LO", "DISPUTED", MODEL_REASON), table=TABLE)
    code2 = rs.assess(verdict("code2", "R-LO"), table=TABLE)
    assert ids(rs.rank([code, model, code2])) == ["model", "code", "code2"]


def test_real_occurrence_breaks_ties():
    t = {"R-LO": ("minor", "s")}
    a = rs.assess(verdict("a", "R-LO"), table=t, real_counts={"R-LO": {"k": 1, "n": 100}})
    b = rs.assess(verdict("b", "R-LO"), table=t, real_counts={"R-LO": {"k": 9, "n": 100}})
    assert ids(rs.rank([a, b])) == ["b", "a"]


# ---- run + disclaimer
def test_drop_is_not_assessed_and_output_has_disclaimer():
    vs = [verdict("a", "R-HI"), verdict("d", "R-HI", "drop", "quote not found in the OCR text"),
          verdict("b", "R-LO", "DISPUTED", MODEL_REASON)]
    ranked = rs.run(vs, table=TABLE)
    assert ids(ranked) == ["a", "b"]
    text = rs.render(ranked)
    assert text.rstrip().endswith(DISC)
    assert EX in text


def test_disclaimer_missing_is_caught(monkeypatch):
    assert rs.DISCLAIMER == DISC
    monkeypatch.setattr(rs, "DISCLAIMER", "")
    assert DISC not in rs.render([])


# ---- docs and licence
def test_docs_citations_and_no_overclaim():
    d = (ROOT / "docs" / "RISK_STEP.md").read_text(encoding="utf-8")
    assert "10.1186/1472-6963-12-150" in d and "10.1002/acm2.70674" in d
    assert "abstract" in d.lower()
    assert not re.search(r"proven|validated|validates", d, re.I)
    assert not re.search(r"\d\s*%", d)


def test_no_8_word_run_from_dynamic_rpn():
    mine = (ROOT / "risk_step.py").read_text(encoding="utf-8")
    files = list((ROOT.parent / "dynamic_rpn" / "src").rglob("*.py"))
    assert files
    for f in files:
        assert not fw.shared_run(mine, f.read_text(encoding="utf-8"), 8), f.name


def test_run_check_itself_can_fail():
    s = "one two three four five six seven eight nine"
    assert fw.shared_run(s, "x " + s, 8)


def test_standard_library_only():
    src = (ROOT / "risk_step.py").read_text(encoding="utf-8")
    mods = set(re.findall(r"^(?:import|from)\s+(\w+)", src, re.M))
    assert mods <= {"sys", "json", "argparse", "re", "pathlib", "sqlite3"}, mods


def test_selftest_passes():
    assert rs.selftest() == 0
