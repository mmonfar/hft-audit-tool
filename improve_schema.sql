-- Self-improvement gate tables (hft-team-12). Two new append-only tables.
-- Kept in its own file, like chain_schema.sql, because tests/test_schema.py pins schema.sql to exactly
-- 14 tables and 28 triggers. The 14 old tables and the log are not changed.
-- Rows in agent_versions come from a human step only (a later card). The gate never writes there.
CREATE TABLE IF NOT EXISTS agent_versions (
  version_id TEXT PRIMARY KEY,
  parent_id TEXT NOT NULL DEFAULT '',
  prompt_hashes TEXT NOT NULL,
  lesson_ids TEXT NOT NULL,
  thresholds TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_digest TEXT NOT NULL,
  runtime_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  result TEXT NOT NULL,
  approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
  signed_by_owner TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS agent_versions_no_update BEFORE UPDATE ON agent_versions
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on agent_versions'); END;
CREATE TRIGGER IF NOT EXISTS agent_versions_no_delete BEFORE DELETE ON agent_versions
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on agent_versions'); END;

-- The gate writes only 'reject' or 'eligible'. It never approves.
CREATE TABLE IF NOT EXISTS gate_results (
  result_id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('reject','eligible')),
  b INTEGER NOT NULL,
  c INTEGER NOT NULL,
  p REAL NOT NULL,
  reasons TEXT NOT NULL,
  protocol_id TEXT NOT NULL,
  ts TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS gate_results_no_update BEFORE UPDATE ON gate_results
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on gate_results'); END;
CREATE TRIGGER IF NOT EXISTS gate_results_no_delete BEFORE DELETE ON gate_results
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on gate_results'); END;
