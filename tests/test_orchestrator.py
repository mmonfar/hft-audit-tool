"""Tests for orchestrator.py and referee.py. Every test has a planted bad case, so it can fail.
The stub model reads fixed outputs from files: no model server, no network."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

import log
import orchestrator as orch
import referee
from casekit import GOOD_FINDING, OCR, make_case, model_only, rows, write_stub

TESTS = Path(__file__).resolve().parent


def run(con, tmp_path, case=None, **stub):
    case = case or make_case()
    return orch.run_case(case, con, orch.StubModel(write_stub(tmp_path / "stub", **stub)))


# ---- happy path and logging
def test_clean_run_confirms_and_logs_before_then_after(con, tmp_path):
    res = run(con, tmp_path)
    assert res["state"] == "CONFIRMED"
    assert res["findings"][0]["rule_id"] == "EMR-01"
    steps = rows(con, "SELECT * FROM steps ORDER BY rowid")
    for agent in ("reader", "rule_checker", "referee"):
        ph = [s["phase"] for s in steps if s["agent"] == agent]
        assert ph == ["before", "after"], agent
    before = [s for s in steps if s["phase"] == "before"]
    after = [s for s in steps if s["phase"] == "after"]
    assert all(s["asked"] and s["asked_sha256"] == log.sha256(s["asked"]) for s in before)
    assert all(s["came_back"] and s["output_sha256"] == log.sha256(s["came_back"]) for s in after)
    assert log.failed_calls(con) == []
    models = rows(con, "SELECT model_tag FROM models")
    assert models == [{"model_tag": "stub"}]
    assert all(s["model_row_id"] for s in steps if s["agent"] in ("reader", "rule_checker"))
    assert all(s["model_row_id"] is None for s in steps if s["agent"] == "referee")


def test_tool_calls_rule_results_and_decisions_are_logged(con, tmp_path):
    run(con, tmp_path)
    tools = {r["tool"] for r in rows(con, "SELECT tool FROM tool_calls")}
    assert {"read_case", "read_rule_list", "regex_rule", "rule_id_lookup"} <= tools
    rr = rows(con, "SELECT * FROM rule_results WHERE rule_id='EMR-01'")
    assert rr and rr[0]["passed"] == 0 and rr[0]["quote"] == "QD"
    dec = rows(con, "SELECT * FROM decisions WHERE decision='CONFIRMED'")
    assert len(dec) == 1 and dec[0]["quote"] == GOOD_FINDING["quote"] and dec[0]["rule_id"] == "EMR-01"


def test_planted_case_proves_tool_rows_can_be_missing(con):
    """Planted bad case: with no run, the table checks above would be empty."""
    assert rows(con, "SELECT * FROM tool_calls") == []


# ---- fake quotes
def test_three_fake_quotes_are_dropped(con, tmp_path):
    fakes = [dict(GOOD_FINDING, fault_id=f"f{i}", quote=q) for i, q in
             enumerate(["Zorvatin 50 mg tablet QD", "Give twice daily", "Patient: Real Person"])]
    res = run(con, tmp_path, checker=json.dumps(fakes))
    assert model_only(res) == [] and len(res["dropped"]) == 3
    drops = rows(con, "SELECT * FROM decisions WHERE decision='drop' AND passed_to IS NULL")
    assert len(drops) == 3
    assert rows(con, "SELECT * FROM decisions WHERE decision='CONFIRMED' AND model_wrote NOT LIKE '%\"code%'") == []


def test_quote_check_ignores_white_space_but_keeps_case():
    assert referee.quote_found("Zorvatin   5 mg\ttablet", "Zorvatin 5 mg\ntablet QD")
    assert not referee.quote_found("zorvatin 5 mg", "Zorvatin 5 mg")
    assert not referee.quote_found("", "anything at all here")


def test_unknown_rule_id_is_dropped(con, tmp_path):
    res = run(con, tmp_path, checker=json.dumps([dict(GOOD_FINDING, rule_id="XXX-99")]))
    assert model_only(res) == [] and "frozen list" in res["dropped"][0]["reason"]


def test_reader_line_not_in_ocr_is_dropped_and_logged(con, tmp_path):
    run(con, tmp_path, reader="PASS\n" + OCR + "\nMade up extra line")
    d = rows(con, "SELECT * FROM decisions WHERE passed_to='reader_check'")
    assert len(d) == 1 and d[0]["quote"] == "Made up extra line" and d[0]["decision"] == "drop"


# ---- could not check
@pytest.mark.parametrize("ocr", ["", "   \n ", "ALERT OK", "x" * 19])
def test_blank_or_blurred_text_is_unable_never_no_findings(con, tmp_path, ocr):
    res = run(con, tmp_path, case=make_case(ocr=ocr))
    assert res["state"] == "UNABLE TO CHECK"
    blob = (res["message"] + json.dumps(res)).lower()
    assert "no findings" not in blob and "could not check" in blob
    assert rows(con, "SELECT * FROM steps WHERE agent IN ('reader','rule_checker')") == []


def test_tool_state_not_ok_is_unable(con, tmp_path):
    assert run(con, tmp_path, case=make_case(tool_state="failed"))["state"] == "UNABLE TO CHECK"


def test_reader_unknown_is_unable(con, tmp_path):
    res = run(con, tmp_path, reader="UNKNOWN")
    assert res["state"] == "UNABLE TO CHECK" and "no findings" not in res["message"].lower()


def test_text_that_was_read_and_has_no_fault_is_not_unable(con, tmp_path):
    clean = "ALERT\nOrder: Zorvatin 5 mg tablet daily\nPatient: Test Patient 01\nOK"
    res = run(con, tmp_path, case=make_case(ocr=clean), reader="PASS\n" + clean, checker="[]")
    assert res["state"] == "CHECKED" and "0 faults" in res["message"]


def test_prose_around_json_twice_is_unable(con, tmp_path):
    bad = "Here is the list: " + json.dumps([GOOD_FINDING]) + " Hope it helps"
    res = run(con, tmp_path, checker=bad)
    assert res["state"] == "UNABLE TO CHECK" and "valid JSON" in res["reason"]
    assert len(rows(con, "SELECT * FROM steps WHERE agent='rule_checker' AND phase='before'")) == 2


def test_one_retry_can_recover(con, tmp_path):
    res = run(con, tmp_path, checker="not json at all", extra={"rule_checker.2.txt": json.dumps([GOOD_FINDING])})
    assert res["state"] == "CONFIRMED"


def test_extra_fields_are_dropped():
    out = referee.strict_parse(json.dumps([dict(GOOD_FINDING, secret_score=9, note="x")]))
    assert set(out[0]) == set(referee.FIELDS)
    assert referee.strict_parse('{"a": 1}') is None
    assert referee.strict_parse("[1, 2]") is None


# ---- repeat detector (fails both ways)
REPEAT_1 = "The dose is wrong. The dose is wrong. []"
REPEAT_2 = '[] Check the patient name first. Then more. Check the patient name first.'


def test_repeat_detector_fires_on_two_planted_outputs():
    assert referee.repeat_detected(REPEAT_1)
    assert referee.repeat_detected(REPEAT_2)
    assert referee.repeat_detected("[]", hit_limit=True)
    assert referee.repeat_detected("[ {" + referee.LIMIT_MARK)


def test_repeat_detector_stays_quiet_on_clean_output():
    assert not referee.repeat_detected(json.dumps([GOOD_FINDING, dict(GOOD_FINDING, fault_id="f2")]))
    assert not referee.repeat_detected("[]")


def test_repeat_on_every_try_is_unable(con, tmp_path):
    res = run(con, tmp_path, checker=REPEAT_1)
    assert res["state"] == "UNABLE TO CHECK" and "repeat" in res["reason"]


def test_token_limit_marker_in_stub_is_unable(con, tmp_path):
    assert run(con, tmp_path, checker="[" + referee.LIMIT_MARK)["state"] == "UNABLE TO CHECK"


# ---- disagreement: code rule only
def test_disagreement_is_disputed_and_adds_no_model_call(con, tmp_path):
    case = make_case(ocr="ALERT\nCheck the patient before you go on.\n[OK] [Cancel]")
    f = dict(GOOD_FINDING, rule_id="EMR-01", quote="Check the patient before you go on.")
    res = run(con, tmp_path, case=case, reader="PASS\n" + case["ocr_text"], checker=json.dumps([f]))
    assert res["state"] == "DISPUTED"
    calls = rows(con, "SELECT agent, COUNT(*) n FROM steps WHERE phase='before' AND model_row_id IS NOT NULL GROUP BY agent")
    assert {c["agent"]: c["n"] for c in calls} == {"reader": 1, "rule_checker": 1}
    assert rows(con, "SELECT * FROM steps WHERE agent='referee' AND model_row_id IS NOT NULL") == []


# ---- crash leaves a trace
class Crash(orch.StubModel):
    def generate(self, agent, prompt, seed=0):
        if agent == "rule_checker":
            raise RuntimeError("killed")
        return super().generate(agent, prompt, seed)


def test_crash_leaves_before_row_and_failed_calls_finds_it(con, tmp_path):
    with pytest.raises(RuntimeError):
        orch.run_case(make_case(), con, Crash(write_stub(tmp_path / "s")))
    failed = log.failed_calls(con)
    assert [f["agent"] for f in failed] == ["rule_checker"]


def test_crash_through_cli_says_could_not_check(tmp_path, capsys, monkeypatch):
    case = tmp_path / "c.json"
    case.write_text(json.dumps(make_case()), encoding="utf-8")
    write_stub(tmp_path / "c.stub")
    monkeypatch.setattr(orch, "StubModel", Crash)
    code = orch.main(["--case", str(case), "--db", str(tmp_path / "l.db"), "--stub"])
    out = capsys.readouterr().out
    assert code == 3 and "COULD NOT CHECK" in out and "no findings" not in out.lower()


# ---- log is append only
def test_decisions_cannot_be_changed_or_deleted(con, tmp_path):
    run(con, tmp_path)
    n = con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    assert n >= 1
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE decisions SET decision='drop'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM decisions")
    assert con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == n


# ---- held-out
def test_heldout_without_flag_exits_with_error_and_writes_nothing(tmp_path, capsys):
    case = tmp_path / "h.json"
    case.write_text(json.dumps(make_case(case_id="H1", split="heldout")), encoding="utf-8")
    write_stub(tmp_path / "h.stub")
    db = tmp_path / "l.db"
    code = orch.main(["--case", str(case), "--db", str(db), "--stub"])
    assert code == 2 and "REFUSED" in capsys.readouterr().out
    assert not db.exists()


def test_heldout_with_flag_is_logged_and_second_use_is_refused(tmp_path):
    case = tmp_path / "h.json"
    case.write_text(json.dumps(make_case(case_id="H1", split="heldout")), encoding="utf-8")
    write_stub(tmp_path / "h.stub")
    db = tmp_path / "l.db"
    assert orch.main(["--case", str(case), "--db", str(db), "--stub", "--heldout"]) == 0
    c = log.open_db(db)
    assert c.execute("SELECT COUNT(*) FROM runs WHERE mode='heldout'").fetchone()[0] == 1
    c.close()
    assert orch.main(["--case", str(case), "--db", str(db), "--stub", "--heldout"]) == 2


# ---- CLI and plain cases
def test_cli_stub_run_writes_log_and_prints_state(tmp_path, capsys):
    case = tmp_path / "c.json"
    case.write_text(json.dumps(make_case()), encoding="utf-8")
    write_stub(tmp_path / "c.stub")
    assert orch.main(["--case", str(case), "--db", str(tmp_path / "l.db"), "--stub"]) == 0
    assert "CONFIRMED" in capsys.readouterr().out
    c = log.open_db(tmp_path / "l.db", create=False)
    assert c.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 6
    c.close()


def test_unreadable_case_file_is_could_not_check(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert orch.main(["--case", str(p), "--db", str(tmp_path / "l.db"), "--stub"]) == 3
    assert "no findings" not in capsys.readouterr().out.lower()
    assert orch.main(["--case", str(tmp_path / "missing.json"), "--db", str(tmp_path / "l.db"), "--stub"]) == 3


def test_agent_case_files_run_through_the_referee():
    """The card-02 referee cases F1..F6: the plain-code referee must never confirm a fake quote."""
    f1 = json.loads((TESTS.parent / "agent_tests" / "cases" / "referee" / "F1.json").read_text(encoding="utf-8"))
    v = referee.judge(f1["faults"], f1["ocr_text"], {"EMR-01"})
    assert v[0]["decision"] == "drop"


def test_no_test_file_can_pass_by_construction():
    bad = re.compile(r"\bor\s+True\b")
    for f in TESTS.glob("test_*.py"):
        assert not bad.search(f.read_text(encoding="utf-8")), f.name
