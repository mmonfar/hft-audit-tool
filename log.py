"""Log writer for the audit log. Standard library only. No network, no model call."""
import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent / "schema.sql"
CHAIN_SCHEMA = Path(__file__).resolve().parent / "chain_schema.sql"
CHAINED = ("steps", "tool_calls", "rule_results", "decisions", "human_severity")  # tables whose rows get a hash link
GENESIS = "0" * 64


def sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def open_db(path=":memory:", create=True):
    """Open the database. With create=True, build it from schema.sql if it is empty."""
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    has = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='steps'").fetchone()[0]
    if not has:
        if not create:
            con.close()
            raise FileNotFoundError("database has no tables")
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
    # log_chain lives in its own file so the 13 old tables stay as they are
    con.executescript(CHAIN_SCHEMA.read_text(encoding="utf-8"))
    return con


# ---------------------------------------------------------------- hash link
# NOTE: the link SHOWS edits to rows. It does not stop someone who rewrites the whole file.
def _row_text(con, table, rowid):
    r = con.execute(f"SELECT * FROM {table} WHERE rowid=?", (rowid,)).fetchone()
    return None if r is None else json.dumps(list(r), default=str)


def _row_hash(prev_hash, table, rowid, text):
    return sha256(f"{prev_hash}|{table}|{rowid}|{text}")


def link_row(con, table, rowid):
    """Write the chain link for a row just inserted. Call before commit: same transaction as the row."""
    if table not in CHAINED:
        raise ValueError(f"table {table} is not chained")
    last = con.execute("SELECT row_hash FROM log_chain ORDER BY chain_seq DESC LIMIT 1").fetchone()
    prev = last[0] if last else GENESIS
    con.execute("INSERT INTO log_chain (table_name, row_id, prev_hash, row_hash) VALUES (?,?,?,?)",
                (table, rowid, prev, _row_hash(prev, table, rowid, _row_text(con, table, rowid))))


def verify_chain(con):
    """Return (ok, row_count, broken). broken is None or a plain text naming the first broken row."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='log_chain'").fetchone():
        return False, 0, "log_chain table is missing"
    prev, n, linked = GENESIS, 0, set()
    for c in con.execute("SELECT * FROM log_chain ORDER BY chain_seq").fetchall():
        n += 1
        who = f"{c['table_name']} row {c['row_id']} (chain_seq {c['chain_seq']})"
        text = _row_text(con, c["table_name"], c["row_id"])
        if c["prev_hash"] != prev:
            return False, n, f"{who}: link to the row before does not match (a row was removed or changed)"
        if text is None:
            return False, n, f"{who}: row is missing"
        if c["row_hash"] != _row_hash(prev, c["table_name"], c["row_id"], text):
            return False, n, f"{who}: row was edited"
        prev = c["row_hash"]
        linked.add((c["table_name"], c["row_id"]))
    for t in CHAINED:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
            continue  # a log made before this table existed
        for r in con.execute(f"SELECT rowid FROM {t} ORDER BY rowid").fetchall():
            if (t, r[0]) not in linked:
                return False, n, f"{t} row {r[0]}: row has no link"
    return True, n, None


def verify_file(path):
    """Print OK and the row count, or the first broken row. Return the exit code."""
    if not Path(path).is_file():
        print(f"BROKEN: database file not found: {path}")
        return 1
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        ok, n, broken = verify_chain(con)
    except sqlite3.DatabaseError as e:
        ok, n, broken = False, 0, f"database cannot be read ({e})"
    con.close()
    print(f"OK {n} rows" if ok else f"BROKEN: {broken}")
    return 0 if ok else 1


def selftest():
    """Build a small synthetic db, check it passes, edit one row in a copy, check it fails."""
    with tempfile.TemporaryDirectory() as d:
        good, bad = Path(d) / "good.db", Path(d) / "bad.db"
        con = open_db(str(good))
        add_case(con, "S1", "alert", "dev", sha256("x"))
        con.execute("INSERT INTO runs VALUES ('r1','2026-01-01T00:00:00','dv','sh','dev','off',0,'selftest')")
        con.commit()
        for i, ph in enumerate(("before", "after"), 1):
            write_step(con, ph, f"s{i}", "r1", "S1", "reader", 1, f"2026-01-01T00:00:0{i}",
                       asked="q" if ph == "before" else None, came_back="a" if ph == "after" else None)
        con.close()
        print("good copy:", end=" ")
        if verify_file(good) != 0:
            return 1
        bad.write_bytes(good.read_bytes())
        c = sqlite3.connect(str(bad))
        c.execute("DROP TRIGGER steps_no_update")
        c.execute("UPDATE steps SET came_back='edited' WHERE step_id='s2'")
        c.commit()
        c.close()
        print("edited copy:", end=" ")
        if verify_file(bad) != 1:
            print("SELFTEST FAILED: an edit was not seen")
            return 1
    print("SELFTEST PASSED: good copy OK, edited copy refused")
    return 0


def add_case(con, case_id, kind, split, input_hash, planted="none", fault_types=None):
    con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?)",
                (case_id, kind, fault_types, planted, split, input_hash))
    con.commit()


def write_step(con, phase, step_id, run_id, case_id, agent, seq, ts,
               asked=None, came_back=None):
    """Write one step row and commit at once. Write 'before' first, 'after' second."""
    if phase not in ("before", "after"):
        raise ValueError("phase must be 'before' or 'after'")
    cur = con.execute(
        "INSERT INTO steps (step_id, run_id, case_id, agent, phase, seq, asked, asked_sha256,"
        " came_back, output_sha256, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (step_id, run_id, case_id, agent, phase, seq, asked,
         sha256(asked) if asked is not None else None,
         came_back, sha256(came_back) if came_back is not None else None, ts))
    link_row(con, "steps", cur.lastrowid)
    con.commit()


SEVERITY_LEVELS = ("minor", "major", "critical")
# A reader id starting with one of these (any case) is a model or an agent, not a person.
NON_HUMAN_PREFIXES = ("model", "agent", "gpt", "llm", "claude", "stub",
                      "reader", "rule_checker", "rule-checker", "referee", "watcher", "finder")


def add_human_severity(con, severity_id, decision_id, fault_id, reader_id, severity, reason, ts):
    """Add one human severity row (append-only, hash-linked). A changed severity is a new row.
    Refuses a model or agent reader, a level outside minor/major/critical, and an empty reason."""
    who = (reader_id or "").strip()
    if not who:
        raise ValueError("reader_id is required")
    if who.lower().startswith(NON_HUMAN_PREFIXES):
        raise ValueError(f"reader_id '{who}' looks like a model or agent; only a person may set a severity")
    if severity not in SEVERITY_LEVELS:
        raise ValueError("severity must be one of " + "/".join(SEVERITY_LEVELS))
    if not (reason or "").strip():
        raise ValueError("reason is required")
    cur = con.execute("INSERT INTO human_severity VALUES (?,?,?,?,?,?,?)",
                      (severity_id, decision_id, fault_id, who, severity, reason.strip(), ts))
    link_row(con, "human_severity", cur.lastrowid)
    con.commit()


def failed_calls(con):
    """Every 'before' row with no 'after' row for the same run, case, agent and seq."""
    rows = con.execute(
        "SELECT b.step_id, b.run_id, b.case_id, b.agent, b.seq, b.ts FROM steps b "
        "WHERE b.phase='before' AND NOT EXISTS (SELECT 1 FROM steps a WHERE a.phase='after' "
        "AND a.run_id=b.run_id AND a.case_id=b.case_id AND a.agent=b.agent AND a.seq=b.seq) "
        "ORDER BY b.ts").fetchall()
    return [dict(r, label="FAILED CALL") for r in rows]


def overlapping_pairs(con):
    """Pairs of calls whose before..after spans overlap. Calls must run one at a time.
    Returns the step_id of each 'before' row. Touching ends do not count as overlap."""
    spans = con.execute(
        "SELECT b.step_id AS sid, b.ts AS t0, a.ts AS t1 FROM steps b JOIN steps a "
        "ON a.phase='after' AND a.run_id=b.run_id AND a.case_id=b.case_id "
        "AND a.agent=b.agent AND a.seq=b.seq WHERE b.phase='before' ORDER BY b.ts").fetchall()
    out = []
    for i, x in enumerate(spans):
        for y in spans[i + 1:]:
            if x["t0"] < y["t1"] and y["t0"] < x["t1"]:
                out.append((x["sid"], y["sid"]))
    return out


def store_protocol(con, protocol_id, text, dated_at):
    con.execute("INSERT INTO protocol VALUES (?,?,?,?)", (protocol_id, sha256(text), dated_at, text))
    con.commit()


def first_heldout_start(con):
    return con.execute("SELECT MIN(started_at) FROM runs WHERE mode='heldout'").fetchone()[0]


def protocol_check(con):
    """Pass only if a protocol exists and every protocol row is dated no later than
    the first held-out run."""
    first = first_heldout_start(con)
    if first is None:
        return True, "no held-out run yet"
    rows = con.execute("SELECT protocol_id, dated_at FROM protocol").fetchall()
    if not rows:
        return False, "no protocol stored before held-out run"
    late = [r["protocol_id"] for r in rows if r["dated_at"] > first]
    if late:
        return False, f"protocol dated later than first held-out run ({first}): {', '.join(late)}"
    return True, "protocol dated before first held-out run"


def heldout_status(con, design_version):
    """OPEN (no run), USED (one run), SPENT (two or more)."""
    n = con.execute("SELECT COUNT(*) FROM runs WHERE mode='heldout' AND design_version=?",
                    (design_version,)).fetchone()[0]
    return "OPEN" if n == 0 else ("USED" if n == 1 else "SPENT")


def register_heldout_run(con, run_id, started_at, design_version, split_hash, seed=None):
    """One held-out run per design. A second is refused: returns SPENT, writes nothing."""
    if heldout_status(con, design_version) != "OPEN":
        return "SPENT"
    con.execute("INSERT INTO runs VALUES (?,?,?,?,'heldout','off',?,NULL)",
                (run_id, started_at, design_version, split_hash, seed))
    con.commit()
    return "OK"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit log tools. The hash link shows edits; it does not stop a full rewrite.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--verify", metavar="DB", help="check the hash link of a log file: prints OK and the row count, or the first broken row (exit 1)")
    g.add_argument("--verify-selftest", action="store_true", help="prove the check can fail, on a synthetic copy")
    a = ap.parse_args(argv)
    return selftest() if a.verify_selftest else verify_file(a.verify)


if __name__ == "__main__":
    sys.exit(main())
