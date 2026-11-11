# hft-audit-tool

![The web screen of the tool on a made-up drug label. Banners at the top say: pilot, made-up case, not a medical device, not reviewed by a human, no accuracy figure. On the left, the sample label has a numbered box 1 around "Take 1 tablet QD". On the right, the decision panel shows the quote, the decision CONFIRMED, what the model suggested (rule EMR-01) and the code rule result: pattern "QD" found inside the quote.](docs/readme_hero.png)

A local pre-check for human factors review of medication labels and alerts. It runs on one computer, uses made-up cases only, and never replaces a human factors engineer. Every output says NOT REVIEWED.

Status: pilot. The full tool is here and it works on made-up cases. Models suggest findings. Code rules decide which findings stay.

What the repo holds:

- The tool: three agent steps (reader, rule checker, referee) in `orchestrator.py`, `referee.py`, `risk_step.py` and the agent prompts in `agents/`.
- The audit log: SQLite schema (`schema.sql`, `chain_schema.sql`) and the log writer with a hash link (`log.py`).
- The web screen: a local server (`server.py`) and the page in `web/`. It shows each run as a live record or a replay.
- The pilot: 20 made-up cases and the runner in `pilot/`.
- The design and specs: `docs/sdd.md` and `docs/specs/`.
- The tests: `tests/` (pytest).

Run the tests:

    python -m pytest -q tests

Run the web demo (fake model, no network):

    python pilot/run_pilot.py --stub --out-dir demo_run
    python server.py demo_run/audit_log_pilot.sqlite --replay

Then open the address it prints (http://127.0.0.1:8765/). The server listens on this computer only. Press Ctrl+C to stop it.

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
