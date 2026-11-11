# Spec: SQLite log

One file, `audit_log.sqlite`, made from `schema.sql`. 14 tables (the last, `human_severity`, was added in hft-team-09). Append-only.

## Rules
1. A BEFORE trigger on every table refuses UPDATE. Another refuses DELETE. Each raises "append-only".
2. A status change is a new row. `lessons` key is (lesson_id, version, status). `watcher_proposals` key is (proposal_id, status).
3. A person's verdict goes in `human_verdicts`. A correction is a new row. The latest row wins in a view; old rows stay.
4. A call writes a `steps` row with phase `before`, then one with phase `after`. A `before` with no `after` is a FAILED CALL.
5. A decision of `keep` or `CONFIRMED` needs a non-empty `quote` or `rule_id`. The database refuses it otherwise.
6. Allowed `decision` values: keep, drop, agree, disagree, cannot tell, CONFIRMED, DISPUTED, UNABLE TO CHECK.
7. Dates are ISO 8601 text.

## Tables and columns
| Table | Columns |
|---|---|
| runs | run_id, started_at, design_version, split_hash, mode (dev/heldout/pilot), lessons_mode (off/on), seed, host_note |
| cases | case_id, kind (label/alert), fault_types, planted (none/fake_quote/unreadable/repeat/bc_disagree), split (dev/heldout), input_hash |
| prompts | prompt_id, agent, version, text, sha256, created_at |
| models | model_row_id, model_tag, model_version, family, temperature, seed |
| steps | step_id, run_id, case_id, agent, phase (before/after), seq, model_row_id, prompt_id, prompt_sha256, asked, asked_sha256, came_back, output_sha256, ts |
| tool_calls | tool_call_id, step_id, tool, args, result, ts |
| rule_results | rr_id, step_id, rule_id, quote, passed (0/1), reason |
| decisions | decision_id, step_id, agent, decision, quote, rule_id, passed_to, model_wrote |
| human_verdicts | verdict_id, decision_id, reader_id, verdict, note, ts |
| lessons | lesson_id, version, text, source_ref, fault_type, status (proposed/approved/retired), created_by, approved_by, ts |
| lesson_use | step_id, lesson_id, lesson_version |
| watcher_proposals | proposal_id, kind (prompt/rule/lesson), target, diff, evidence_steps, status, ts |
| protocol | protocol_id, sha256, dated_at, text |

## Checks
See `tests/test_schema.py`.
