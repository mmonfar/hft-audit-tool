"""Tests for hft-team-08: the five referee fixes. NEW synthetic sentences only (not the pilot case text).
Every test can fail: each one checks a planted bad input. No model call.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "framework"), str(ROOT / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

import framework as fw  # noqa: E402
import referee  # noqa: E402

RULES = {"EMR-01", "EMR-02", "ALT-01", "ALT-02", "ALT-03", "NIE-03"}


def f(rule, quote, fid="f1"):
    return dict(fault_id=fid, rule_id=rule, quote=quote, location="l", severity="major",
                confidence=0.8, audience="nurse")


def full(findings, text, item_type=None):
    v = referee.judge(findings, text, RULES, item_type)
    return referee.add_code_findings(v, text, item_type, RULES)


# ---- fix 1: a regex hit with no model finding becomes its own finding
def test_fix1_trailing_zero_found_by_code_alone():
    out = full([], "Zorvane 2.0 mg capsule\nTake one at night")
    assert len(out) == 1 and out[0]["decision"] == "CONFIRMED"
    assert out[0]["finding"]["rule_id"] == "EMR-01" and out[0]["finding"]["quote"] == "2.0 mg"
    assert out[0]["reason"] == "found by code rule, no model finding"


def test_fix1_no_leading_zero_found_by_code_alone():
    out = full([], "Tavelin .25 mg tablet\nTake one daily")
    assert [(v["finding"]["quote"], v["decision"]) for v in out] == [(".25 mg", "CONFIRMED")]


def test_fix1_clean_text_gets_no_code_finding():
    assert full([], "Tavelin 0.25 mg tablet\nTake one daily") == []


def test_fix1_model_finding_is_not_doubled():
    out = full([f("EMR-01", "Zorvane 2.0 mg capsule")], "Zorvane 2.0 mg capsule\nTake one at night")
    assert len(out) == 1 and out[0]["reason"] != "found by code rule, no model finding"


# ---- fix 2: regex hit must sit inside the quoted span
def test_fix2_hit_outside_quote_is_disputed():
    text = "ALERT: Rexan level is high\n[Close]"
    v = referee.judge([f("ALT-03", "ALERT: Rexan level is high")], text, RULES, "alert")
    assert v[0]["decision"] == "DISPUTED"


def test_fix2_hit_inside_quote_is_confirmed():
    text = "ALERT: Rexan level is high\n[Close]"
    v = referee.judge([f("ALT-03", "ALERT: Rexan level is high [Close]")], text, RULES, "alert")
    assert v[0]["decision"] == "CONFIRMED"


# ---- fix 3: rule must apply to the item type
def test_fix3_error_rule_dropped_on_plain_alert():
    text = "Warning: low supply of Nolmax\n[Order more] [Ignore]"
    v = referee.judge([f("NIE-03", "Warning: low supply of Nolmax")], text, RULES, "alert")
    assert v[0]["decision"] == "drop" and v[0]["reason"] == "rule does not apply to this item type"


def test_fix3_alert_rule_dropped_on_error_message():
    text = "Error 17\nSave failed.\n[Retry]"
    v = referee.judge([f("ALT-01", "Save failed.")], text, RULES, "error_message")
    assert v[0]["decision"] == "drop" and v[0]["reason"] == "rule does not apply to this item type"


def test_fix3_error_rule_kept_on_error_message():
    text = "Error 17\nSave failed.\n[Retry]"
    v = referee.judge([f("NIE-03", "Save failed.")], text, RULES, "error_message")
    assert v[0]["decision"] == "CONFIRMED"


def test_fix3_item_type_from_text():
    assert referee.classify_item("Error 9\nSomething failed.", "alert") == "error_message"
    assert referee.classify_item("Warning: low supply\n[Order]", "alert") == "alert"
    assert referee.classify_item("Zorvane 2.0 mg", "label") == "label"
    assert referee.classify_item("Zorvane 2.0 mg", None) is None


def test_fix3_every_ruled_criterion_has_applies_to_and_source():
    data = fw.load()
    ruled = [c for c in data["criteria"] if c["rule_id"]]
    assert ruled
    for c in ruled:
        assert c["applies_to"] and c["applies_to_source"].startswith("RULE_CATALOGUE.md")
    m = fw.applies_map(data)
    assert m["NIE-03"] == {"error_message"} and "error_message" not in m["ALT-01"]


def test_fix3_framework_load_fails_without_source():
    data = fw.load()
    bad = copy.deepcopy(data)
    for c in bad["criteria"]:
        if c["rule_id"] == "ALT-01":
            c["applies_to_source"] = ""
    errs, _ = fw.validate(bad, {c["rule_id"] for c in bad["criteria"] if c["rule_id"]}, {c["source"] for c in bad["criteria"]})
    assert any("applies_to_source" in e for e in errs)
    bad2 = copy.deepcopy(data)
    for c in bad2["criteria"]:
        if c["rule_id"] == "ALT-01":
            del c["applies_to"]
    errs, _ = fw.validate(bad2, {c["rule_id"] for c in bad2["criteria"] if c["rule_id"]}, {c["source"] for c in bad2["criteria"]})
    assert any("applies_to must" in e for e in errs)


# ---- fix 4: ALT-02 needs two or more alerts to compare
def test_fix4_single_alert_word_is_not_alt02():
    text = "CAUTION\nRead the order again.\n[Continue] [Back]"
    v = referee.judge([f("ALT-02", "CAUTION")], text, RULES, "alert")
    assert v[0]["decision"] == "drop" and "two or more alerts" in v[0]["reason"]


def test_fix4_two_alerts_keep_alt02():
    text = "WARNING Dose is high\n[Ok]\nWARNING Dose is low\n[Ok]"
    v = referee.judge([f("ALT-02", "WARNING Dose is high")], text, RULES, "alert")
    assert v[0]["decision"] == "CONFIRMED"


# ---- fix 5: tall-man names are not an EMR-02 fault
def test_fix5_tall_man_list_not_emr02():
    text = "Pick list\nVelmoDINE 5 mg\nVelmoDONE 5 mg\nVelmotin 5 mg"
    v = referee.judge([f("EMR-02", "VelmoDINE 5 mg\nVelmoDONE 5 mg")], text, RULES, "label")
    assert v[0]["decision"] == "drop" and "tall-man" in v[0]["reason"]


def test_fix5_plain_lookalikes_still_emr02():
    text = "Pick list\nVelmodine 5 mg\nVelmodone 5 mg"
    v = referee.judge([f("EMR-02", "Velmodine 5 mg\nVelmodone 5 mg")], text, RULES, "label")
    assert v[0]["decision"] == "CONFIRMED"


# ---- old traps still pass
def test_traps_fake_quote_dropped():
    v = referee.judge([f("ALT-01", "This text is not in the page")], "Real page text, long enough here", RULES, "alert")
    assert v[0]["decision"] == "drop" and "not found" in v[0]["reason"]


def test_traps_repeat_caught():
    t = "The dose is wrong now. The dose is wrong now. Please look."
    assert referee.repeat_detected(t)


def test_traps_unreadable_gives_unable(tmp_path):
    import log
    import orchestrator

    class M:
        tag = "stub"

        def generate(self, a, p, seed=0):
            return "UNKNOWN", False

        def name_next_check(self, k, o):
            return None
    con = log.open_db(str(tmp_path / "x.sqlite"))
    r = orchestrator.run_case(dict(case_id="Z1", kind="label", split="dev", ocr_text="x"), con, M())
    assert r["state"] == "UNABLE TO CHECK"
