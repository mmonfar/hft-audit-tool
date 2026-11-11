-- Hash link for the log rows. One new table; the 13 tables in schema.sql are not changed.
-- Kept in its own file because tests/test_schema.py pins schema.sql to exactly 13 tables and 26 triggers.
-- log.open_db loads it after schema.sql. The link SHOWS edits; it does not stop a full rewrite of the file.
CREATE TABLE IF NOT EXISTS log_chain (
  chain_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL,
  row_id INTEGER NOT NULL,
  prev_hash TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS log_chain_no_update BEFORE UPDATE ON log_chain
BEGIN SELECT RAISE(ABORT, 'append-only: UPDATE refused on log_chain'); END;
CREATE TRIGGER IF NOT EXISTS log_chain_no_delete BEFORE DELETE ON log_chain
BEGIN SELECT RAISE(ABORT, 'append-only: DELETE refused on log_chain'); END;
