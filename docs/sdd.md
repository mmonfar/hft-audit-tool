# SDD: hft-audit-tool

## Goal
Build a local pre-check that finds human factors faults in made-up medication labels and alerts, and measure how repeatable it is. A person reads every item. Output always says NOT REVIEWED.

## Scope (this step)
- This spec, the log spec, `schema.sql` and `tests/`.
- An append-only SQLite log with 13 tables (see `docs/specs/log_schema.md`).

## Out of scope
- Any code that runs a model, a server, agents, statistics or a reader study.
- Real or de-identified data. Cases are synthetic only.
- Any outside network use. Only loopback (127.0.0.1) is allowed in later steps.
- Claims of safety, clinical benefit or fitness for real use.

## Rules decide
Models only suggest. A finding stands only with an exact quote found in the source text, or a known rule id. A missing quote and rule id means the finding is dropped. If reading failed, the state is UNABLE TO CHECK, never "no findings".

## The 20-case pilot
- 20 made-up cases, 3 runs each (60 case-runs). Lessons off for the first pass, on for the second.
- Planted cases inside the 20: 3 fake quote, 3 unreadable, 2 repeated sentence, 1 disagreement between two checkers.
- The dev and held-out split is fixed and hashed before any prompt work. For the pilot the held-out part stays closed.
- The pilot is labelled "pilot, not a result". It is reported as counts (3 of 3, 2 of 3, 1 of 3) with percent beside them.

## Reliability target (proposal)
Proposal: kappa over 0.8, tool against the reference, with a 95% interval. The exact target and the analysis are fixed in a protocol that is written and dated before any held-out case is run. The protocol hash and date are stored in the `protocol` table.

## Stop rule
- 2 failed checks on one build step: go up one level, then stop and report in one line.
- No third try in a loop.
- If the readers' kappa stays under the target after the marking rules are fixed once, stop and report. No tool figure is quoted.

## Checks for this step
`tests/test_schema.py` proves: 13 tables with fixed column names; UPDATE and DELETE are refused on every table and row counts stay the same; the licence files name AGPL-3.0-or-later, CC BY-NC 4.0 and the disclaimer; only standard library and pytest are imported; the refusal tests can fail (triggers removed in a copy, the change then goes through).

## Purpose
Show a person, in plain words, what the pre-check did with one case: what the models suggested, what the code rules decided, and why. The screen is read only. It never changes the log.

## Contract and interfaces
- Input: the append-only SQLite log. The screen opens it read only.
- Server (`server.py`): 127.0.0.1 only. GET routes only: `/view`, `/api/rule_results/<run>`, `/api/decisions/<run>`, `/api/human_severity/<run>`, `/api/log_chain`, `/api/runs`, `/events`. Every write verb is refused (405).
- Modes: LIVE follows a running case. REPLAY plays a saved run and always carries the label REPLAY with its speed.
- Truth rule: every decision on the screen is judged by today's `referee.py` from the logged model output. No model call. The old verdict in the log is not shown as today's.
- Five end states, each with a word and a shape: CONFIRMED, DISPUTED, DROPPED, UNABLE TO CHECK, CHECKED.
- Always-on labels: pilot, made-up case, not reviewed, not a medical device, no accuracy figure.

## Acceptance criteria
- A CONFIRMED row has a code pattern hit inside the model's quote. A DISPUTED row has the hit outside it. A planted wrong badge fails the test.
- UNABLE TO CHECK never says "no findings" and shows why in plain words.
- No outside request. No banned names. No number in the risk cell from a model.
- Raw JSON, "regex", "OCR" and tool states appear only in the technical drawer.
- Text is 24 px or more at 1920 x 1080.

## Tests
`tests/test_live_screen.py` (routes, modes, five states, labels, no outside request, badge-agrees-with-referee), `tests/test_server.py`, and the other files in `tests/`. Screenshots: `python docs/screens/make_screens.py`.

## Specs
Design files: `design/hft/live_record_screen_*.md` in the Housekeeping folder. Log spec: `docs/specs/`.

## Test gate for self-improvement (hft-team-12)
Code-only gate that decides if a hand-written change is eligible; it never approves and uses no model. Spec: `docs/specs/improve_gate.md`; tests: `tests/test_improve_gate.py`; run: `python scripts/evaluate_candidate.py --practice`.

## Illustrative redesign view (hft-team-13)
Goal: after the findings, show a fictional redesign for CONFIRMED findings only. The rule-to-fix table is one data file, `redesign_table.py`, with fixed words and no model. Spec: `docs/specs/redesign.md`; tests: `tests/test_redesign_table.py` (table part green, render part waits for the screen build).
