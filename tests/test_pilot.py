"""Tests for the 20-case pilot (card hft-team-04). All use --stub: no model server, no network.
Every check has a planted bad case, so it can fail. Synthetic data only.

Expected answers (written before any run):
- 20 cases, all split dev: 12 fault, 4 clean, 2 unreadable, 2 traps. No held-out case.
- stub run: fault cases found 12 of 12, clean 4 of 4 clean, unreadable 2 of 2 UNABLE TO CHECK,
  fake-quote trap dropped, repeat trap UNABLE TO CHECK.
"""
import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot"
for p in (str(ROOT), str(PILOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import log  # noqa: E402
import make_cases  # noqa: E402
import run_pilot  # noqa: E402


@pytest.fixture
def built(tmp_path):
    cdir = tmp_path / "cases"
    make_cases.build(cdir)
    return cdir


def run_stub(cdir, out, *extra):
    return run_pilot.main(["--stub", "--cases-dir", str(cdir), "--out-dir", str(out), *extra])


def result_of(out):
    return json.loads((Path(out) / "pilot_result.json").read_text(encoding="utf-8"))


# ---- the case set
def test_mix_is_12_4_2_2_all_dev(built):
    cases = run_pilot.load_cases(built)
    assert len(cases) == 20
    assert all(c["split"] == "dev" for c in cases)
    groups = [c["group"] for c in cases]
    assert groups.count("fault") == 12 and groups.count("clean") == 4
    assert groups.count("unreadable") == 2
    assert groups.count("trap_fake_quote") == 1 and groups.count("trap_repeat") == 1
    for c in cases:
        assert (built / f"{c['case_id']}.ocr.txt").is_file()
        assert (built / f"{c['case_id']}.expected.json").is_file()


def test_fault_ids_come_from_the_rule_list(built):
    import orchestrator
    ids = set(orchestrator.load_rules())
    for c in run_pilot.load_cases(built):
        if c["group"] == "fault":
            assert c["expected"]["rule_id"] in ids


def test_a_planted_heldout_case_is_refused_before_any_call(built, tmp_path):
    bad = json.loads((built / "P01.json").read_text(encoding="utf-8"))
    bad["case_id"], bad["split"] = "P99", "heldout"
    (built / "P99.json").write_text(json.dumps(bad), encoding="utf-8")
    (built / "P99.ocr.txt").write_text("x" * 40, encoding="utf-8")
    (built / "P99.expected.json").write_text("{}", encoding="utf-8")
    out = tmp_path / "out"
    assert run_stub(built, out) == 2
    assert not (out / "pilot_run.sqlite").exists() or \
        sqlite3.connect(out / "pilot_run.sqlite").execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_a_file_named_heldout_is_refused(built, tmp_path):
    (built / "heldout_01.json").write_text("{}", encoding="utf-8")
    assert run_stub(built, tmp_path / "out") == 2


# ---- full stub run
def test_full_stub_run_counts_and_states(built, tmp_path):
    out = tmp_path / "out"
    assert run_stub(built, out) == 0
    r = result_of(out)
    assert r["status"] == "COMPLETE" and r["cases_done"] == 20
    assert r["counts"]["found"]["value"] == "12 of 12"
    assert r["counts"]["missed"]["value"] == "0 of 12"
    assert r["counts"]["false_alarms"]["value"] == "0 of 20"
    assert r["counts"]["unable_to_check"]["value"] == "3 of 20"
    by = {c["case_id"]: c for c in r["per_case"]}
    assert len(by) == 20
    for c in by.values():
        assert "expected" in c and "final" in c and c["outcome"]
    assert (out / "audit_log_pilot.sqlite").is_file()


def test_every_figure_is_labelled_pilot_and_no_accuracy_key(built, tmp_path):
    out = tmp_path / "out"
    run_stub(built, out)
    r = result_of(out)
    assert run_pilot.forbidden_keys(r) == []
    for v in r["counts"].values():
        assert v["label"] == "PILOT, 20 made-up development cases, one run"
    text = (out / "pilot_result.json").read_text(encoding="utf-8")
    assert "%" not in text


def test_planted_accuracy_key_is_caught():
    bad = {"counts": {"found": {"value": "1 of 12"}}, "detail": [{"Accuracy": 0.9}, {"percent_ok": 1}]}
    assert run_pilot.forbidden_keys(bad) == ["Accuracy", "percent_ok"]


def test_unreadable_cases_end_unable_to_check(built, tmp_path):
    out = tmp_path / "out"
    run_stub(built, out)
    r = result_of(out)
    un = [c for c in r["per_case"] if c["group"] == "unreadable"]
    assert len(un) == 2 and all(c["final"]["state"] == "UNABLE TO CHECK" for c in un)
    assert all(c["outcome"] == "correct_unable" for c in un)


def test_planted_no_findings_for_unreadable_is_flagged():
    expected = {"group": "unreadable", "expected_state": "UNABLE TO CHECK"}
    planted = {"state": "CHECKED", "findings": [], "dropped": [], "reason": None}
    assert run_pilot.score_case(expected, planted)["outcome"] == "WRONG_CLEAN"
    ok = {"state": "UNABLE TO CHECK", "findings": [], "dropped": [], "reason": "x"}
    assert run_pilot.score_case(expected, ok)["outcome"] == "correct_unable"


def test_traps(built, tmp_path):
    out = tmp_path / "out"
    run_stub(built, out)
    r = result_of(out)
    fake = next(c for c in r["per_case"] if c["group"] == "trap_fake_quote")
    assert fake["final"]["findings"] == [] and len(fake["final"]["dropped"]) == 1
    assert fake["outcome"] == "trap_caught"
    rep = next(c for c in r["per_case"] if c["group"] == "trap_repeat")
    assert rep["final"]["state"] == "UNABLE TO CHECK" and "repeat" in rep["final"]["reason"]
    assert rep["outcome"] == "trap_caught"


def test_planted_trap_that_passes_is_flagged():
    fake = {"group": "trap_fake_quote", "expected_state": "CHECKED", "trap_quote": "Give double dose now"}
    leaked = {"state": "CONFIRMED", "findings": [{"rule_id": "EMR-01", "quote": "Give double dose now",
                                                  "state": "CONFIRMED"}], "dropped": [], "reason": None}
    assert run_pilot.score_case(fake, leaked)["outcome"] == "trap_failed"
    rep = {"group": "trap_repeat", "expected_state": "UNABLE TO CHECK"}
    assert run_pilot.score_case(rep, {"state": "CHECKED", "findings": [], "dropped": [],
                                      "reason": None})["outcome"] == "trap_failed"


# ---- log checks
def test_log_has_no_overlap_no_failed_call_no_heldout_and_only_stub_model(built, tmp_path):
    out = tmp_path / "out"
    run_stub(built, out)
    con = log.open_db(str(out / "pilot_run.sqlite"), create=False)
    assert log.overlapping_pairs(con) == []
    assert log.failed_calls(con) == []
    assert con.execute("SELECT COUNT(*) FROM runs WHERE mode='heldout'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM cases WHERE split!='dev'").fetchone()[0] == 0
    tags = {r[0] for r in con.execute("SELECT model_tag FROM models")}
    assert run_pilot.models_ok(tags)
    assert log.verify_chain(con)[0] is True


def test_planted_overlap_and_medgemma_are_caught(tmp_path):
    con = log.open_db(":memory:")
    for sid, t0, t1 in (("a", "2026-01-01T00:00:00", "2026-01-01T00:10:00"),
                        ("b", "2026-01-01T00:05:00", "2026-01-01T00:12:00")):
        con.execute("INSERT INTO runs VALUES (?,?,?,?,'dev','off',0,'x')", (f"r{sid}", t0, "d", "h"))
        con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?)", (f"c{sid}", "label", None, "none", "dev", "h"))
        for ph, ts in (("before", t0), ("after", t1)):
            log.write_step(con, ph, f"{sid}-{ph}", f"r{sid}", f"c{sid}", "reader", 1, ts, "asked", "back")
    assert log.overlapping_pairs(con) != []
    assert not run_pilot.models_ok({"gpt-oss:20b", "medgemma:4b"})
    assert run_pilot.models_ok({"gpt-oss:20b"}) and run_pilot.models_ok({"stub"})


# ---- expected answers fixed before the run
def test_expected_hash_in_runs_row_and_dated_before_first_step(built, tmp_path):
    out = tmp_path / "out"
    run_stub(built, out)
    con = log.open_db(str(out / "pilot_run.sqlite"), create=False)
    hashes = json.loads((built / "EXPECTED_HASH.json").read_text(encoding="utf-8"))
    dated = hashes["dated_at"]
    rows = con.execute("SELECT run_id, host_note FROM runs").fetchall()
    assert len(rows) == 20
    for run_id, note in rows:
        assert note.startswith("pilot expected_sha256=")
        sha = note.split("=", 1)[1]
        assert sha in hashes["files"].values()
        first = con.execute("SELECT MIN(ts) FROM steps WHERE run_id=?", (run_id,)).fetchone()[0]
        assert dated < first


def test_edited_expected_file_is_refused(built, tmp_path):
    f = built / "P01.expected.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["rule_id"] = "ALT-01"  # changed after the hash was taken
    d["expected_state"] = "CHECKED"
    f.write_text(json.dumps(d), encoding="utf-8")
    out = tmp_path / "out"
    assert run_stub(built, out) == 2
    assert not (out / "pilot_result.json").exists()


# ---- save as you go and resume
def test_resume_loses_at_most_one_case(built, tmp_path):
    out = tmp_path / "out"
    assert run_stub(built, out, "--stop-after", "7") == 0
    r = result_of(out)
    assert r["status"] == "RUNNING" and r["cases_done"] == 7
    assert len(list((out / "results").glob("*.json"))) == 7
    assert not (out / "audit_log_pilot.sqlite").exists()
    assert run_stub(built, out) == 0
    r2 = result_of(out)
    assert r2["status"] == "COMPLETE" and r2["cases_done"] == 20
    con = sqlite3.connect(out / "pilot_run.sqlite")
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 20  # 7 not run twice


def test_lost_case_is_run_again_on_resume(built, tmp_path):
    out = tmp_path / "out"
    run_stub(built, out, "--stop-after", "5")
    (out / "results" / "P03.json").unlink()  # a stop lost this case
    run_stub(built, out)
    assert result_of(out)["cases_done"] == 20
    con = sqlite3.connect(out / "pilot_run.sqlite")
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 21  # only the lost case ran twice


# ---- names
def test_no_banned_name_in_cases(built):
    for c in run_pilot.load_cases(built):
        assert make_cases.banned_hits(c["ocr_text"]) == []


def test_planted_real_looking_name_is_caught():
    assert make_cases.banned_hits("Tylenol 500 mg tablet") != []
    assert make_cases.banned_hits("Zorvatin 5 mg tablet") == []


# ---- note
def test_note_has_required_lines():
    text = (PILOT / "PILOT_NOTE.md").read_text(encoding="utf-8")
    assert run_pilot.note_problems(text) == []


def test_planted_bad_note_is_caught():
    assert run_pilot.note_problems("Pilot result: 90 accuracy.") != []


def test_repo_cases_match_the_generator(tmp_path):
    """The committed cases are the generated ones, and their expected files match the recorded hash."""
    fresh = tmp_path / "fresh"
    make_cases.build(fresh)
    for f in sorted(fresh.glob("*.json")):
        if f.name == "EXPECTED_HASH.json":
            continue
        assert (PILOT / "cases" / f.name).read_text(encoding="utf-8") == f.read_text(encoding="utf-8"), f.name
    assert run_pilot.check_expected_hash(PILOT / "cases") == []
