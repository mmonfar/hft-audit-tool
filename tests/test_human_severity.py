"""Human severity row tests (hft-team-09). Synthetic data only."""
import json
import shutil
import sqlite3

import pytest

import log
import risk_step as rs
import orchestrator as orch
from casekit import make_case, write_stub


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "audit.db"
    con = log.open_db(str(p))
    orch.run_case(make_case(), con, orch.StubModel(write_stub(tmp_path / "stub")))
    did = con.execute("SELECT decision_id FROM decisions LIMIT 1").fetchone()[0]
    con.close()
    return p, did


def add(con, did, sid="h1", fault="f1", reader="alice", sev="major", reason="clinical judgement", ts="2026-11-10T09:00:00"):
    return log.add_human_severity(con, sid, did, fault, reader, sev, reason, ts)


def count(con):
    return con.execute("SELECT COUNT(*) FROM human_severity").fetchone()[0]


def test_insert_works_and_is_chained(db):
    p, did = db
    con = log.open_db(str(p))
    add(con, did)
    r = con.execute("SELECT * FROM human_severity").fetchone()
    assert r["severity"] == "major" and r["reader_id"] == "alice" and r["fault_id"] == "f1"
    assert con.execute("SELECT COUNT(*) FROM log_chain WHERE table_name='human_severity'").fetchone()[0] == 1
    assert log.verify_chain(con)[0]


def test_update_and_delete_refused(db):
    p, did = db
    con = log.open_db(str(p))
    add(con, did)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE human_severity SET severity='minor'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM human_severity")
    assert count(con) == 1


def test_bad_level_refused(db):
    p, did = db
    con = log.open_db(str(p))
    with pytest.raises(ValueError):
        add(con, did, sev="catastrophic")
    with pytest.raises(sqlite3.IntegrityError):  # the table itself also refuses
        con.execute("INSERT INTO human_severity VALUES ('x',?,'f','alice','huge','why','t')", (did,))
    assert count(con) == 0


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_empty_reason_refused(db, reason):
    p, did = db
    con = log.open_db(str(p))
    with pytest.raises(ValueError):
        add(con, did, reason=reason)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO human_severity VALUES ('x',?,'f','alice','major',?, 't')", (did, reason or ""))
    assert count(con) == 0


@pytest.mark.parametrize("reader", ["model", "gpt-oss:20b", "agent_reader", "Agent-1", "referee", "reader",
                                    "rule_checker", "", None])
def test_model_or_agent_reader_refused(db, reader):
    p, did = db
    con = log.open_db(str(p))
    with pytest.raises(ValueError):
        add(con, did, reader=reader)
    assert count(con) == 0


def test_unknown_decision_refused(db):
    p, _ = db
    con = log.open_db(str(p))
    with pytest.raises(sqlite3.IntegrityError):
        add(con, "no-such-decision")
    assert count(con) == 0


def test_chain_fails_when_row_changed_by_hand(db, tmp_path):
    p, did = db
    con = log.open_db(str(p))
    add(con, did)
    con.close()
    bad = tmp_path / "bad.db"
    shutil.copy(p, bad)
    c = sqlite3.connect(str(bad))
    c.execute("DROP TRIGGER human_severity_no_update")
    c.execute("UPDATE human_severity SET severity='minor'")
    c.commit()
    c.close()
    assert log.verify_file(p) == 0
    assert log.verify_file(bad) == 1


def test_row_without_link_is_seen(db, tmp_path):
    p, did = db
    con = log.open_db(str(p))
    add(con, did)
    con.close()
    bad = tmp_path / "bad2.db"
    shutil.copy(p, bad)
    c = sqlite3.connect(str(bad))
    c.execute("INSERT INTO human_severity VALUES ('sneak',?,'f1','bob','critical','x','t')", (did,))
    c.commit()
    c.close()
    assert log.verify_file(bad) == 1


def verdict(fid, rule="R-NONE", model_sev=None):
    f = {"fault_id": fid, "rule_id": rule, "quote": "q"}
    if model_sev is not None:
        f["severity"] = model_sev
    return {"finding": f, "decision": "CONFIRMED", "reason": "quote found, rule id valid"}


def test_risk_step_uses_latest_human_row(db):
    p, did = db
    con = log.open_db(str(p))
    add(con, did, sid="h1", sev="minor", reader="alice", ts="2026-11-09T09:00:00")
    add(con, did, sid="h2", sev="critical", reader="bob", ts="2026-11-10T10:00:00", reason="changed my mind")
    con.close()
    rows = rs.load_human_rows(str(p))
    out = rs.run([verdict("f1", model_sev=3)], human_rows=rows)
    s = out[0]["severity"]
    assert s["value"] == "critical" and s["source"] == "human entry"
    assert s["reader_id"] == "bob" and s["date"] == "2026-11-10" and s["earlier"] == 1
    text = rs.render(out)
    assert "human entry" in text and "bob" in text and "2026-11-10" in text and "earlier entries: 1" in text
    assert out[0]["severity_proposal"]["label"] == "PROPOSAL (model), not a score"


def test_model_severity_stays_proposal_without_human_row(db):
    p, _ = db
    out = rs.run([verdict("f1", model_sev=9)], human_rows=rs.load_human_rows(str(p)))
    assert out[0]["severity"]["value"] is None and out[0]["severity_proposal"]["value"] == 9


def test_json_path_still_works():
    out = rs.run([verdict("f1")], human_rows=[{"fault_id": "f1", "severity": "major"}])
    assert out[0]["severity"]["value"] == "major" and out[0]["severity"]["source"] == "human entry"
    assert "earlier" not in rs.render(out)


def test_cli_db_and_json_together(db, tmp_path, capsys):
    p, did = db
    con = log.open_db(str(p))
    add(con, did, sev="critical")
    con.close()
    vf, hf = tmp_path / "v.json", tmp_path / "h.json"
    vf.write_text(json.dumps([verdict("f1"), verdict("f2")]), encoding="utf-8")
    hf.write_text(json.dumps([{"fault_id": "f2", "severity": "minor"}]), encoding="utf-8")
    assert rs.main(["--verdicts", str(vf), "--db", str(p), "--human", str(hf)]) == 0
    text = capsys.readouterr().out
    assert "critical" in text and "minor" in text and "alice" in text


def test_missing_db_is_plain_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        rs.load_human_rows(str(tmp_path / "missing.db"))
