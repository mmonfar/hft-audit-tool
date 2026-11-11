# Spec: log writer (`log.py`)

Standard library only. No model call, no network.

## What it does
1. `open_db(path)` builds the database from `schema.sql`.
2. `write_step` writes a `before` row first, then an `after` row. Each write is committed at once, so a crash keeps the `before` row.
3. `failed_calls` lists each `before` row with no `after` row (same run, case, agent, seq) as FAILED CALL.
4. `overlapping_pairs` reports calls whose before..after spans overlap. Model calls run one at a time. Touching ends are not an overlap.
5. `store_protocol` stores the protocol text, its sha256 and its date.
6. `first_heldout_start` returns the earliest `runs.started_at` where mode is `heldout`, or None.
7. `protocol_check` fails when no protocol exists, or when any protocol row is dated later than that time. An amendment after the first held-out run also fails.
8. `register_heldout_run` allows one held-out run per `design_version` (the design hash). A second returns SPENT and writes nothing. `heldout_status` gives OPEN, USED or SPENT.

## Checks
See `tests/test_log.py`. Each planted bad case must fail the check it targets.
