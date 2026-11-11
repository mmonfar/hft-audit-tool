"""Schema tests. Synthetic rows only. Stdlib + pytest."""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "schema.sql").read_text(encoding="utf-8")

EXPECTED = {
    "runs": ["run_id", "started_at", "design_version", "split_hash", "mode", "lessons_mode", "seed", "host_note"],
    "cases": ["case_id", "kind", "fault_types", "planted", "split", "input_hash"],
    "prompts": ["prompt_id", "agent", "version", "text", "sha256", "created_at"],
    "models": ["model_row_id", "model_tag", "model_version", "family", "temperature", "seed"],
    "steps": ["step_id", "run_id", "case_id", "agent", "phase", "seq", "model_row_id", "prompt_id",
              "prompt_sha256", "asked", "asked_sha256", "came_back", "output_sha256", "ts"],
    "tool_calls": ["tool_call_id", "step_id", "tool", "args", "result", "ts"],
    "rule_results": ["rr_id", "step_id", "rule_id", "quote", "passed", "reason"],
    "decisions": ["decision_id", "step_id", "agent", "decision", "quote", "rule_id", "passed_to", "model_wrote"],
    "human_verdicts": ["verdict_id", "decision_id", "reader_id", "verdict", "note", "ts"],
    "lessons": ["lesson_id", "version", "text", "source_ref", "fault_type", "status", "created_by", "approved_by", "ts"],
    "lesson_use": ["step_id", "lesson_id", "lesson_version"],
    "watcher_proposals": ["proposal_id", "kind", "target", "diff", "evidence_steps", "status", "ts"],
    "protocol": ["protocol_id", "sha256", "dated_at", "text"],
    "human_severity": ["severity_id", "decision_id", "fault_id", "reader_id", "severity", "reason", "ts"],
}

# One synthetic row per table, in insert order (foreign keys on).
ROWS = [
    ("runs", "('r1','2026-01-01T00:00:00','dv1','sh1','pilot','off',1,'x')"),
    ("cases", "('c1','label','look-alike','none','dev','ih1')"),
    ("prompts", "('p1','finder','v1','text','h1','2026-01-01T00:00:00')"),
    ("models", "('m1','tag','dg1','fam',0.0,1)"),
    ("steps", "('s1','r1','c1','finder','before',1,'m1','p1','h1','q','qh',NULL,NULL,'2026-01-01T00:00:01')"),
    ("tool_calls", "('t1','s1','ocr','a','r','2026-01-01T00:00:02')"),
    ("rule_results", "('rr1','s1','R1','quote',1,'ok')"),
    ("decisions", "('d1','s1','finder','keep','quote','R1','referee','note')"),
    ("human_verdicts", "('v1','d1','reader1','agree','n','2026-01-01T00:00:03')"),
    ("lessons", "('l1',1,'text','src','look-alike','proposed','tester',NULL,'2026-01-01T00:00:04')"),
    ("lesson_use", "('s1','l1',1)"),
    ("watcher_proposals", "('w1','prompt','finder','diff','s1','proposed','2026-01-01T00:00:05')"),
    ("protocol", "('pr1','sha','2026-01-01T00:00:06','protocol text')"),
    ("human_severity", "('hs1','d1','f1','reader1','major','because','2026-01-01T00:00:07')"),
]


def make_db(schema=SCHEMA):
    con = sqlite3.connect(":memory:")
    con.executescript(schema)
    for t, vals in ROWS:
        con.execute(f"INSERT INTO {t} VALUES {vals}")
    con.commit()
    return con


def count(con, t):
    return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]


def test_fourteen_tables_exact_names():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == set(EXPECTED)
    assert len(names) == 14


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_column_names_match_plan(table):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    assert cols == EXPECTED[table]


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_update_refused_and_count_same(table):
    con = make_db()
    col = EXPECTED[table][1]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute(f"UPDATE {table} SET {col} = {col}")
    assert count(con, table) == 1


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_delete_refused_and_count_same(table):
    con = make_db()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute(f"DELETE FROM {table}")
    assert count(con, table) == 1


def test_two_triggers_per_table():
    names = re.findall(r"CREATE TRIGGER (\w+)", SCHEMA)
    assert len(names) == 28
    for t in EXPECTED:
        assert f"{t}_no_update" in names and f"{t}_no_delete" in names


def test_tests_can_fail_without_triggers():
    """Proof the refusal tests bite: with triggers removed, UPDATE and DELETE succeed."""
    bare = re.sub(r"CREATE TRIGGER.*?END;", "", SCHEMA, flags=re.S)
    assert "CREATE TRIGGER" not in bare
    con = make_db(bare)
    con.execute("UPDATE runs SET host_note = 'changed'")
    assert con.execute("SELECT host_note FROM runs").fetchone()[0] == "changed"
    con.execute("DELETE FROM protocol")
    assert count(con, "protocol") == 0


def test_status_change_is_new_row():
    con = make_db()
    con.execute("INSERT INTO lessons VALUES ('l1',1,'text','src','look-alike','approved','tester','boss','2026-01-02T00:00:00')")
    rows = con.execute("SELECT status FROM lessons WHERE lesson_id='l1' ORDER BY ts").fetchall()
    assert [r[0] for r in rows] == ["proposed", "approved"]


def test_finding_without_quote_or_rule_refused():
    con = make_db()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO decisions VALUES ('d2','s1','finder','keep','',NULL,'referee','x')")
    con.execute("INSERT INTO decisions VALUES ('d3','s1','finder','drop',NULL,NULL,'none','x')")
    assert count(con, "decisions") == 2


def test_bad_phase_refused():
    con = make_db()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO steps VALUES ('s9','r1','c1','a','middle',2,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'t')")


def test_licence_pack_wording():
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in lic
    for name in ("LICENSING.md", "README.md"):
        txt = (ROOT / name).read_text(encoding="utf-8")
        assert "AGPL-3.0-or-later" in txt, name
        assert "CC BY-NC 4.0" in txt, name
        assert "not a medical device" in txt.lower(), name
        assert "Independence and data notice" in txt, name
    assert "commercial licence" in (ROOT / "LICENSING.md").read_text(encoding="utf-8").lower()


def test_layout_files_exist():
    for p in ("docs/sdd.md", "docs/specs/log_schema.md", "schema.sql", "LICENSE", "LICENSING.md", "README.md"):
        assert (ROOT / p).is_file(), p


def test_imports_are_stdlib_or_pytest():
    own_modules = {p.stem for p in ROOT.glob("*.py")} | {p.stem for p in (ROOT / "framework").glob("*.py")} | {p.stem for p in (ROOT / "pilot").glob("*.py")}
    allowed = set(sys.stdlib_module_names) | {"pytest"} | own_modules
    for f in (ROOT / "tests").glob("*.py"):
        for m in re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_]\w*)", f.read_text(encoding="utf-8"), re.M):
            assert m in allowed, (f.name, m)
