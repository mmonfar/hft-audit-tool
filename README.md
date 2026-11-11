# hft-audit-tool

A local pre-check for human factors review of medication labels and alerts. It runs on one computer, uses made-up cases only, and never replaces a human factors engineer. Every output says NOT REVIEWED.

Status: step 1 of a pilot. This repo holds the design (`docs/sdd.md`), the log spec (`docs/specs/log_schema.md`), the SQLite schema (`schema.sql`) and its tests.

Run the tests: `python -m pytest -q tests`

## Licence

- Code: AGPL-3.0-or-later. A commercial licence is available on request. See `LICENSE` and `LICENSING.md`.
- Content (cases, rule text, docs): CC BY-NC 4.0.

AI use: this project is built with AI assistance (code and text drafting); the author reviews the results.

## Not a medical device

This is research software. It is not a medical device. It gives no clinical advice and comes with no warranty and no liability.

Severity levels are set from published human-factors sources. They have not been reviewed by a clinician. Use your own clinical judgement.

## Independence and data notice

This is a personal project, built independently in my own time and on my own equipment. It is not affiliated with, endorsed by, or representative of any employer or other organisation. It holds no employer data, systems, code or confidential information. All data here is synthetic. Any likeness to real people or events is chance. Views are my own.

## Hash link (log_chain)

Each log row (steps, tool_calls, rule_results, decisions) has a link row in `log_chain` (own file `chain_schema.sql`; the 13 tables in `schema.sql` are unchanged). Check a log file:

    python log.py --verify <db>          # prints OK and the row count, or the first broken row; exit 1 if broken
    python log.py --verify-selftest      # proves the check can fail, on a synthetic copy

This link shows edits; it does not stop someone who rewrites the whole file.

## Send-back and next check

A dropped finding goes back once to the rule checker (`MAX_RETRY = 1` in `orchestrator.py`) with the referee reason. The referee judges the reply again; a retry alone never confirms. A garbled reply or failed call gives UNABLE TO CHECK. The next check comes from a fixed list per case type (`CHECKS`); a name outside the list is refused and the default is used.
