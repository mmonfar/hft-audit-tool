-- Append-only audit log. 14 tables. Every table refuses UPDATE and DELETE.
-- A status change (lessons, watcher_proposals) is a NEW row, never an update.
PRAGMA foreign_keys = ON;

CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  design_version TEXT NOT NULL,
  split_hash TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('dev','heldout','pilot')),
  lessons_mode TEXT NOT NULL CHECK (lessons_mode IN ('off','on')),
  seed INTEGER,
  host_note TEXT
);
CREATE TRIGGER runs_no_update BEFORE UPDATE ON runs
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on runs'); END;
CREATE TRIGGER runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on runs'); END;

CREATE TABLE cases (
  case_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('label','alert')),
  fault_types TEXT,
  planted TEXT NOT NULL DEFAULT 'none' CHECK (planted IN ('none','fake_quote','unreadable','repeat','bc_disagree')),
  split TEXT NOT NULL CHECK (split IN ('dev','heldout')),
  input_hash TEXT NOT NULL
);
CREATE TRIGGER cases_no_update BEFORE UPDATE ON cases
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on cases'); END;
CREATE TRIGGER cases_no_delete BEFORE DELETE ON cases
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on cases'); END;

CREATE TABLE prompts (
  prompt_id TEXT PRIMARY KEY,
  agent TEXT NOT NULL,
  version TEXT NOT NULL,
  text TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TRIGGER prompts_no_update BEFORE UPDATE ON prompts
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on prompts'); END;
CREATE TRIGGER prompts_no_delete BEFORE DELETE ON prompts
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on prompts'); END;

CREATE TABLE models (
  model_row_id TEXT PRIMARY KEY,
  model_tag TEXT NOT NULL,
  model_version TEXT NOT NULL,
  family TEXT,
  temperature REAL,
  seed INTEGER
);
CREATE TRIGGER models_no_update BEFORE UPDATE ON models
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on models'); END;
CREATE TRIGGER models_no_delete BEFORE DELETE ON models
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on models'); END;

CREATE TABLE steps (
  step_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  case_id TEXT NOT NULL REFERENCES cases(case_id),
  agent TEXT NOT NULL,
  phase TEXT NOT NULL CHECK (phase IN ('before','after')),
  seq INTEGER NOT NULL,
  model_row_id TEXT REFERENCES models(model_row_id),
  prompt_id TEXT REFERENCES prompts(prompt_id),
  prompt_sha256 TEXT,
  asked TEXT,
  asked_sha256 TEXT,
  came_back TEXT,
  output_sha256 TEXT,
  ts TEXT NOT NULL
);
CREATE TRIGGER steps_no_update BEFORE UPDATE ON steps
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on steps'); END;
CREATE TRIGGER steps_no_delete BEFORE DELETE ON steps
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on steps'); END;

CREATE TABLE tool_calls (
  tool_call_id TEXT PRIMARY KEY,
  step_id TEXT NOT NULL REFERENCES steps(step_id),
  tool TEXT NOT NULL,
  args TEXT,
  result TEXT,
  ts TEXT NOT NULL
);
CREATE TRIGGER tool_calls_no_update BEFORE UPDATE ON tool_calls
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on tool_calls'); END;
CREATE TRIGGER tool_calls_no_delete BEFORE DELETE ON tool_calls
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on tool_calls'); END;

CREATE TABLE rule_results (
  rr_id TEXT PRIMARY KEY,
  step_id TEXT NOT NULL REFERENCES steps(step_id),
  rule_id TEXT NOT NULL,
  quote TEXT,
  passed INTEGER NOT NULL CHECK (passed IN (0,1)),
  reason TEXT
);
CREATE TRIGGER rule_results_no_update BEFORE UPDATE ON rule_results
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on rule_results'); END;
CREATE TRIGGER rule_results_no_delete BEFORE DELETE ON rule_results
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on rule_results'); END;

CREATE TABLE decisions (
  decision_id TEXT PRIMARY KEY,
  step_id TEXT NOT NULL REFERENCES steps(step_id),
  agent TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('keep','drop','agree','disagree','cannot tell','CONFIRMED','DISPUTED','UNABLE TO CHECK')),
  quote TEXT,
  rule_id TEXT,
  passed_to TEXT,
  model_wrote TEXT,
  CHECK (decision NOT IN ('keep','CONFIRMED') OR (COALESCE(quote,'') <> '' OR COALESCE(rule_id,'') <> ''))
);
CREATE TRIGGER decisions_no_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on decisions'); END;
CREATE TRIGGER decisions_no_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on decisions'); END;

CREATE TABLE human_verdicts (
  verdict_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
  reader_id TEXT NOT NULL,
  verdict TEXT NOT NULL,
  note TEXT,
  ts TEXT NOT NULL
);
CREATE TRIGGER human_verdicts_no_update BEFORE UPDATE ON human_verdicts
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on human_verdicts'); END;
CREATE TRIGGER human_verdicts_no_delete BEFORE DELETE ON human_verdicts
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on human_verdicts'); END;

CREATE TABLE lessons (
  lesson_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  text TEXT NOT NULL,
  source_ref TEXT,
  fault_type TEXT,
  status TEXT NOT NULL CHECK (status IN ('proposed','approved','retired')),
  created_by TEXT NOT NULL,
  approved_by TEXT,
  ts TEXT NOT NULL,
  PRIMARY KEY (lesson_id, version, status)
);
CREATE TRIGGER lessons_no_update BEFORE UPDATE ON lessons
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on lessons'); END;
CREATE TRIGGER lessons_no_delete BEFORE DELETE ON lessons
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on lessons'); END;

CREATE TABLE lesson_use (
  step_id TEXT NOT NULL REFERENCES steps(step_id),
  lesson_id TEXT NOT NULL,
  lesson_version INTEGER NOT NULL,
  PRIMARY KEY (step_id, lesson_id, lesson_version)
);
CREATE TRIGGER lesson_use_no_update BEFORE UPDATE ON lesson_use
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on lesson_use'); END;
CREATE TRIGGER lesson_use_no_delete BEFORE DELETE ON lesson_use
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on lesson_use'); END;

CREATE TABLE watcher_proposals (
  proposal_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('prompt','rule','lesson')),
  target TEXT NOT NULL,
  diff TEXT,
  evidence_steps TEXT,
  status TEXT NOT NULL,
  ts TEXT NOT NULL,
  PRIMARY KEY (proposal_id, status)
);
CREATE TRIGGER watcher_proposals_no_update BEFORE UPDATE ON watcher_proposals
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on watcher_proposals'); END;
CREATE TRIGGER watcher_proposals_no_delete BEFORE DELETE ON watcher_proposals
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on watcher_proposals'); END;

CREATE TABLE protocol (
  protocol_id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  dated_at TEXT NOT NULL,
  text TEXT NOT NULL
);
CREATE TRIGGER protocol_no_update BEFORE UPDATE ON protocol
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on protocol'); END;
CREATE TRIGGER protocol_no_delete BEFORE DELETE ON protocol
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on protocol'); END;

-- A human sets a severity for a fault, with a reason. A changed severity is a NEW row.
CREATE TABLE human_severity (
  severity_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
  fault_id TEXT NOT NULL,
  reader_id TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('minor','major','critical')),
  reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  ts TEXT NOT NULL
);
CREATE TRIGGER human_severity_no_update BEFORE UPDATE ON human_severity
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on human_severity'); END;
CREATE TRIGGER human_severity_no_delete BEFORE DELETE ON human_severity
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on human_severity'); END;
