"""Log writer tests. Fake synthetic rows only. Stdlib + pytest."""
import ast
import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import log  # noqa: E402


@pytest.fixture
def con():
    c = log.open_db(":memory:")
    log.add_case(c, "c1", "label", "dev", "ih1")
    return c


def run(c, rid, started, mode="pilot", design="d1"):
    c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
              (rid, started, design, "sh", mode, "off", 1, "x"))


def pair(c, rid, sid, seq, t_before, t_after, agent="finder", with_after=True):
    log.write_step(c, "before", f"{sid}b", rid, "c1", agent, seq, t_before, asked="q")
    if with_after:
        log.write_step(c, "after", f"{sid}a", rid, "c1", agent, seq, t_after, came_back="a")


# --- before / after rows
def test_before_then_after_rows(con):
    run(con, "r1", "2026-01-01T00:00:00")
    pair(con, "r1", "s1", 1, "2026-01-01T00:00:01", "2026-01-01T00:00:02")
    rows = con.execute("SELECT phase FROM steps ORDER BY ts").fetchall()
    assert [r[0] for r in rows] == ["before", "after"]
    assert log.failed_calls(con) == []


def test_hashes_stored(con):
    run(con, "r1", "2026-01-01T00:00:00")
    log.write_step(con, "before", "s1", "r1", "c1", "finder", 1, "2026-01-01T00:00:01", asked="hello")
    got = con.execute("SELECT asked_sha256 FROM steps").fetchone()[0]
    assert got == hashlib.sha256(b"hello").hexdigest()


def test_bad_phase_refused(con):
    run(con, "r1", "2026-01-01T00:00:00")
    with pytest.raises(ValueError):
        log.write_step(con, "middle", "s1", "r1", "c1", "finder", 1, "2026-01-01T00:00:01")


# --- failed call view
def test_before_without_after_is_failed_call(con):
    run(con, "r1", "2026-01-01T00:00:00")
    pair(con, "r1", "s1", 1, "2026-01-01T00:00:01", None, with_after=False)
    pair(con, "r1", "s2", 2, "2026-01-01T00:00:03", "2026-01-01T00:00:04")
    bad = log.failed_calls(con)
    assert len(bad) == 1 and bad[0]["step_id"] == "s1b" and bad[0]["label"] == "FAILED CALL"


def test_kill_between_writes_leaves_failed_call(tmp_path):
    db = tmp_path / "k.sqlite"
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT)!r})
        import log
        c = log.open_db({str(db)!r})
        log.add_case(c, "c1", "label", "dev", "ih1")
        c.execute("INSERT INTO runs VALUES ('r1','2026-01-01T00:00:00','d1','sh','pilot','off',1,'x')")
        log.write_step(c, "before", "s1b", "r1", "c1", "finder", 1, "2026-01-01T00:00:01", asked="q")
        print("WROTE", flush=True)
        time.sleep(60)
        log.write_step(c, "after", "s1a", "r1", "c1", "finder", 1, "2026-01-01T00:00:02")
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "WROTE"
    finally:
        p.kill()
        p.wait()
    c = log.open_db(str(db), create=False)
    assert c.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 1
    bad = log.failed_calls(c)
    assert len(bad) == 1 and bad[0]["label"] == "FAILED CALL"
    c.close()


# --- overlap check
def test_overlapping_pairs_reported(con):
    run(con, "r1", "2026-01-01T00:00:00")
    pair(con, "r1", "s1", 1, "2026-01-01T00:00:01", "2026-01-01T00:00:05")
    pair(con, "r1", "s2", 2, "2026-01-01T00:00:03", "2026-01-01T00:00:08")
    assert log.overlapping_pairs(con) == [("s1b", "s2b")]


def test_sequential_pairs_pass(con):
    run(con, "r1", "2026-01-01T00:00:00")
    pair(con, "r1", "s1", 1, "2026-01-01T00:00:01", "2026-01-01T00:00:03")
    pair(con, "r1", "s2", 2, "2026-01-01T00:00:03", "2026-01-01T00:00:08")
    assert log.overlapping_pairs(con) == []


# --- protocol
def test_protocol_sha_and_date_stored(con):
    log.store_protocol(con, "pr1", "protocol text", "2026-01-01T00:00:00")
    sha, dated = con.execute("SELECT sha256, dated_at FROM protocol").fetchone()
    assert sha == hashlib.sha256(b"protocol text").hexdigest() and dated == "2026-01-01T00:00:00"


def test_first_heldout_time(con):
    run(con, "r0", "2026-01-01T00:00:00", mode="dev")
    run(con, "r2", "2026-03-01T00:00:00", mode="heldout", design="d2")
    run(con, "r1", "2026-02-01T00:00:00", mode="heldout", design="d1")
    assert log.first_heldout_start(con) == "2026-02-01T00:00:00"


def test_first_heldout_none_when_no_heldout(con):
    run(con, "r0", "2026-01-01T00:00:00", mode="dev")
    assert log.first_heldout_start(con) is None


def test_protocol_after_heldout_fails(con):
    run(con, "r1", "2026-02-01T00:00:00", mode="heldout")
    log.store_protocol(con, "pr1", "text", "2026-02-02T00:00:00")
    ok, msg = log.protocol_check(con)
    assert not ok and "later" in msg


def test_protocol_before_heldout_passes(con):
    run(con, "r1", "2026-02-01T00:00:00", mode="heldout")
    log.store_protocol(con, "pr1", "text", "2026-01-31T00:00:00")
    assert log.protocol_check(con)[0] is True


def test_heldout_with_no_protocol_fails(con):
    run(con, "r1", "2026-02-01T00:00:00", mode="heldout")
    ok, msg = log.protocol_check(con)
    assert not ok and "no protocol" in msg


def test_amended_protocol_after_heldout_fails(con):
    run(con, "r1", "2026-02-01T00:00:00", mode="heldout")
    log.store_protocol(con, "pr1", "text", "2026-01-31T00:00:00")
    log.store_protocol(con, "pr2", "text v2", "2026-02-05T00:00:00")
    assert log.protocol_check(con)[0] is False


# --- held-out: one run per design hash
def test_second_heldout_run_same_design_is_spent(con):
    assert log.register_heldout_run(con, "h1", "2026-02-01T00:00:00", "dA", "sh") == "OK"
    assert log.register_heldout_run(con, "h2", "2026-02-02T00:00:00", "dA", "sh") == "SPENT"
    assert con.execute("SELECT COUNT(*) FROM runs WHERE mode='heldout'").fetchone()[0] == 1
    assert log.heldout_status(con, "dA") == "USED"


def test_other_design_still_open(con):
    log.register_heldout_run(con, "h1", "2026-02-01T00:00:00", "dA", "sh")
    assert log.heldout_status(con, "dB") == "OPEN"
    assert log.register_heldout_run(con, "h3", "2026-02-03T00:00:00", "dB", "sh") == "OK"


def test_spent_when_two_rows_already_there(con):
    run(con, "h1", "2026-02-01T00:00:00", mode="heldout", design="dA")
    run(con, "h2", "2026-02-02T00:00:00", mode="heldout", design="dA")
    assert log.heldout_status(con, "dA") == "SPENT"


# --- stdlib only
def test_imports_are_stdlib_only():
    tree = ast.parse((ROOT / "log.py").read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert mods, "no imports found"
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
    assert not (mods & {"socket", "urllib", "http", "requests"})
