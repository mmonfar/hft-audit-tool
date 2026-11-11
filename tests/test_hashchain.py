"""Hash link tests (hft-team-05 c). The link shows edits. It does not stop a full rewrite of the file."""
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

import log
import orchestrator as orch
from casekit import make_case, write_stub

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "audit.db"
    con = log.open_db(str(p))
    orch.run_case(make_case(), con, orch.StubModel(write_stub(tmp_path / "stub")))
    con.close()
    return p


def chained_rows(p):
    c = sqlite3.connect(str(p))
    n = c.execute("SELECT COUNT(*) FROM log_chain").fetchone()[0]
    c.close()
    return n


def tamper(src, dst, sql):
    shutil.copy(src, dst)
    c = sqlite3.connect(str(dst))
    for trig in [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]:
        c.execute(f"DROP TRIGGER {trig}")
    c.execute(sql)
    c.commit()
    c.close()


def test_untouched_db_verifies_ok_with_row_count(db, capsys):
    n = chained_rows(db)
    assert n > 8
    assert log.main(["--verify", str(db)]) == 0
    assert capsys.readouterr().out.strip() == f"OK {n} rows"


def test_one_edited_came_back_exits_1_and_names_the_row(db, tmp_path, capsys):
    bad = tmp_path / "bad.db"
    tamper(db, bad, "UPDATE steps SET came_back='edited' WHERE step_id LIKE '%reader-1-a'")
    c = sqlite3.connect(str(bad))
    rid = c.execute("SELECT rowid FROM steps WHERE step_id LIKE '%reader-1-a'").fetchone()[0]
    c.close()
    assert log.main(["--verify", str(bad)]) == 1
    out = capsys.readouterr().out
    assert f"steps row {rid} " in out and "edited" in out


def test_removed_row_is_seen(db, tmp_path, capsys):
    bad = tmp_path / "bad.db"
    tamper(db, bad, "DELETE FROM tool_calls WHERE rowid=(SELECT MIN(rowid) FROM tool_calls)")
    assert log.main(["--verify", str(bad)]) == 1
    assert "tool_calls row" in capsys.readouterr().out


def test_removed_chain_link_is_seen(db, tmp_path):
    bad = tmp_path / "bad.db"
    tamper(db, bad, "DELETE FROM log_chain WHERE chain_seq=5")
    assert log.main(["--verify", str(bad)]) == 1


def test_row_added_without_a_link_is_seen(db, tmp_path, capsys):
    bad = tmp_path / "bad.db"
    shutil.copy(db, bad)
    c = sqlite3.connect(str(bad))
    c.execute("INSERT INTO decisions VALUES ('x',(SELECT step_id FROM steps LIMIT 1),'referee','drop',NULL,NULL,NULL,'x')")
    c.commit()
    c.close()
    assert log.main(["--verify", str(bad)]) == 1
    assert "no link" in capsys.readouterr().out


def test_missing_file_exits_1(tmp_path):
    assert log.main(["--verify", str(tmp_path / "none.db")]) == 1


@pytest.mark.parametrize("sql", ["UPDATE log_chain SET row_hash='x'", "DELETE FROM log_chain"])
def test_log_chain_refuses_update_and_delete(db, sql):
    c = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        c.execute(sql)
    c.close()


def test_old_tables_and_schema_file_are_unchanged():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "log_chain" not in schema and len(re.findall(r"CREATE TABLE", schema)) == 14
    assert len(re.findall(r"CREATE TRIGGER", schema)) == 28
    chain = (ROOT / "chain_schema.sql").read_text(encoding="utf-8")
    assert "chain_seq INTEGER PRIMARY KEY AUTOINCREMENT" in chain
    assert "log_chain_no_update" in chain and "log_chain_no_delete" in chain


def test_link_is_written_in_the_same_transaction_as_the_row():
    con = log.open_db(":memory:")
    con.execute("INSERT INTO runs VALUES ('r','t','d','h','dev','off',0,NULL)")
    con.execute("INSERT INTO cases VALUES ('c','label',NULL,'none','dev','h')")
    con.commit()
    cur = con.execute("INSERT INTO steps (step_id,run_id,case_id,agent,phase,seq,ts) VALUES ('s','r','c','a','before',1,'t')")
    log.link_row(con, "steps", cur.lastrowid)
    assert con.execute("SELECT COUNT(*) FROM log_chain").fetchone()[0] == 1
    con.rollback()
    assert con.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM log_chain").fetchone()[0] == 0


def test_selftest_passes_and_can_fail(capsys, monkeypatch):
    assert log.main(["--verify-selftest"]) == 0
    assert "SELFTEST PASSED" in capsys.readouterr().out
    monkeypatch.setattr(log, "verify_chain", lambda con: (True, 0, None))   # planted bad checker: sees nothing
    assert log.main(["--verify-selftest"]) == 1
    assert "SELFTEST FAILED" in capsys.readouterr().out


def test_readme_says_shows_edits_and_never_claims_tamper_proof():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "shows edits" in readme and "does not stop someone who rewrites the whole file" in readme
    word = "tamper" + "-proof"
    for f in list(ROOT.glob("*.py")) + list(ROOT.glob("*.md")) + list(ROOT.glob("*.sql")):
        assert word not in f.read_text(encoding="utf-8").lower(), f.name
