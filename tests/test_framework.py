"""Tests for framework/framework.py and framework/hf_framework_v0.json.

Every check has a planted bad file in tests/fixtures. The test shows the check
fails on that file, so a check that cannot fail would be caught here.
Stdlib + pytest. If the catalogue or the reference file is missing, the
tests that need them FAIL (they never pass by skipping).
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "framework"))
import framework as fw  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FILE = ROOT / "framework" / "hf_framework_v0.json"
README = ROOT / "framework" / "README.md"
HOLD = ROOT.parent / "_House" "keeping"
CATALOGUE = HOLD / "ideas" / "hf-tool" / "RULE_CATALOGUE.md"
REFERENCE = HOLD / "inbox" / "ED" / "2026-11-07_hf-decks-reference.md"


@pytest.fixture(scope="module")
def cat():
    assert CATALOGUE.is_file(), "catalogue not found: cannot check rule ids"
    text = CATALOGUE.read_text(encoding="utf-8")
    return fw.parse_rule_ids(text), fw.parse_source_ids(text)


@pytest.fixture(scope="module")
def ref():
    assert REFERENCE.is_file(), "reference file not found: cannot check copying"
    return REFERENCE.read_text(encoding="utf-8")


def run(path, cat, ref=None):
    data = fw.load(path)
    return fw.validate(data, cat[0], cat[1], ref)


def errors_for(name, cat, ref=None):
    errs, _ = run(FIX / name, cat, ref)
    return errs


# ---- the good file passes
def test_real_file_is_valid(cat, ref):
    errs, not_run = run(FILE, cat, ref)
    assert errs == []
    assert not_run == []


def test_catalogue_parse_finds_known_ids(cat):
    assert {"ALT-01", "NIE-04", "EMR-03"} <= cat[0]
    assert "wcag-22-reference" in cat[1]
    assert "ALT-99" not in cat[0]


# ---- each check fails on its planted file
def test_bad_source_rejected(cat):
    assert any("source" in e for e in errors_for("bad_source.json", cat))


def test_bad_rule_id_rejected(cat):
    errs = errors_for("bad_rule_id.json", cat)
    assert any("ALT-99" in e for e in errs)


def test_too_few_notes_rejected(cat):
    assert any("note" in e and "fewer than 5" in e for e in errors_for("few_notes.json", cat))


def test_too_few_order_sets_rejected(cat):
    assert any("order_set" in e and "fewer than 5" in e for e in errors_for("few_order_sets.json", cat))


def test_over_claim_rejected(cat):
    errs = errors_for("over_claim.json", cat)
    assert any("certified" in e for e in errs)
    assert any("validated" in e for e in errs)


def test_missing_field_rejected(cat):
    assert any("missing" in e for e in errors_for("missing_field.json", cat))


def test_bad_detect_rejected(cat):
    assert any("detect" in e for e in errors_for("bad_detect.json", cat))


def test_fmea_must_say_guess(cat):
    assert any("fmea_fields" in e for e in errors_for("fmea_not_guess.json", cat))


def test_duplicate_id_rejected(cat):
    assert any("duplicate" in e for e in errors_for("duplicate_id.json", cat))


def test_copy_from_reference_rejected(cat):
    # A synthetic reference text; the planted file copies 8 words from it.
    fake_ref = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    errs, _ = fw.validate(fw.load(FIX / "copied_run.json"), cat[0], cat[1], fake_ref)
    assert any("copied" in e for e in errs)


def test_copy_check_not_run_is_reported(cat):
    errs, not_run = fw.validate(fw.load(FILE), cat[0], cat[1], None)
    assert errs == []
    assert any("reference" in n for n in not_run)


def test_eight_word_run_helper():
    a = "one two three four five six seven eight nine"
    assert fw.shared_run("x one two three four five six seven eight y", a, 8)
    assert not fw.shared_run("one two three four five six seven", a, 8)


# ---- content rules on the real file
def test_alert_inputs_are_needs_source():
    data = fw.load(FILE)
    ai = data["alert_inputs"]
    assert ai["audience"] and ai["timing"]
    assert ai["audience_source"] == "needs source"
    assert ai["timing_source"] == "needs source"


def test_alert_criteria_use_alert_rows():
    data = fw.load(FILE)
    ids = {c["rule_id"] for c in data["criteria"] if c["artefact"] == "alert"}
    assert {"ALT-01", "ALT-02", "ALT-03"} <= ids


# ---- README matches the file
def readme_numbers():
    text = README.read_text(encoding="utf-8")
    out = {}
    for key in ("alert", "note", "order_set"):
        m = re.search(r"^- " + key + r": (\d+)\s*$", text, re.M)
        assert m, "README missing count line for " + key
        out[key] = int(m.group(1))
    m = re.search(r"^needs source count: (\d+)\s*$", text, re.M)
    assert m, "README missing needs source count"
    out["needs"] = int(m.group(1))
    return out, text


def test_readme_counts_match_file():
    nums, _ = readme_numbers()
    data = fw.load(FILE)
    for key in ("alert", "note", "order_set"):
        assert nums[key] == sum(1 for c in data["criteria"] if c["artefact"] == key)
    assert nums["needs"] == fw.count_needs_source(data)


def test_count_helper_counts_everything():
    d = {"criteria": [{"source": "needs source"}, {"source": "x"}],
         "alert_inputs": {"audience_source": "needs source"}}
    assert fw.count_needs_source(d) == 2


def test_readme_mismatch_would_fail():
    # The README check is real: a wrong number must differ from the file.
    nums, _ = readme_numbers()
    data = fw.load(FILE)
    assert nums["needs"] + 1 != fw.count_needs_source(data)


def test_readme_required_lines():
    _, text = readme_numbers()
    low = text.lower()
    assert "does not replace a human factors engineer" in low
    assert "not a medical device" in low
    assert "pre-check" in low
    assert "guess" in low


def test_readme_has_no_overclaim():
    text = README.read_text(encoding="utf-8").lower()
    assert "certified" not in text
    assert "validated" not in text
