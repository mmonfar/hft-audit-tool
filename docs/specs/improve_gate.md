# Spec: test gate for the safe self-improvement loop (hft-team-12)

Pre-check tool only. Not a medical device. PCCP used as a design reference only. Synthetic cases only.
The gate is code. It imports no model client and makes no network call. It is deterministic.
No proposer is built here: a human writes the candidate. Source: memo 2026-11-10 "self-improving agents", sections 3, 5, 6.
**Every gate number below is a PROPOSAL for the owner.** The gate prints them as proposals.

## Inputs
- A candidate JSON: `candidate_id`, `kind` (prompt_line / lesson / rule_threshold_suggestion), `target` (finder / reader / checker / lesson_list / threshold_note), `text` (300 characters at most).
- A runner `runner(version, split, candidate)` with version old/new and split dev_check/regression. It returns per fault 3 runs `{found, quote, rule_id}`, per clean item 3 runs `{flagged}`, `unable_rate`, `plants` (3 fake_quote and 3 unreadable, caught yes/no), `minutes_per_case`, optional `artifacts` (text to scan).
- A `protocol` row with the gate settings and its sha256. Canary strings. Case texts. Code-rule files to hash.

## Outputs
- One `gate_results` row: candidate id, verdict (`reject` or `eligible` only), B, C, p, reasons, protocol id.
- Printed text with the smallest B that can pass and the word "proposal". "Eligible" always says: not approved; a human must read the diff.
- New tables in `improve_schema.sql` (not in `schema.sql`: `tests/test_schema.py` pins that file to 14 tables, the same reason `chain_schema.sql` is its own file). Both are append-only (no update, no delete): `agent_versions` (written by a human step only; `signed_by_owner` blank) and `gate_results`.

## Gate rules (numbered)
- G1 Hash chain of the log is checked before any run (existing `log.verify_chain`). Broken = refuse. (R9)
- G2 Settings come from the `protocol` row; its text must match its hash. Changed text with the old hash = refuse. (R14)
- G3 At most 3 candidates per round (proposal). More = reject. (R3)
- G4 Candidate: 300 characters at most; kind and target from the fixed lists. (R8)
- G5 Text that says "report nothing", "no findings" or "skip hard cases" is refused. (R5)
- G6 Any 8 words in a row copied from a case text = refused. 7 words are allowed. (R4)
- G7 A lesson is refused when 10 are already active. (R10)
- G8 Canary strings are searched in the candidate and in the runner's prompts, lessons and logs. A hit stops the run. The scan has a test where it must find a planted canary. (R1, R2)
- G9 "Found" = found in at least 2 of 3 runs with a quote or a rule id.
- G10 Size check: old version run first on dev-check. If its misses are fewer than the smallest B that can pass, print "cannot pass, only N misses; grow the set first" and reject. The new version is not run. (R13)
- G11 Paired table B (new only) and C (old only). Exact one-sided McNemar with `math.comb`. With C = 0, p = 0.5^B. (R3)
- G12 Pass level is alpha / candidates (Bonferroni): alpha 0.05 and 3 candidates give B >= 6 with C = 0 (p 0.0156). B = 5 (p 0.031) fails. Any C above 0 on dev-check or on the regression set rejects. (R6, R7)
- G13 Must not worsen: false alarms at most baseline +1 per 30 clean items; UNABLE TO CHECK rate must not fall; the 3 fake-quote and 3 unreadable plants still caught; time at most +25%; code-rule file hashes the same at start and end. (R5, R8)
- G14 A check that could not run (missing run file, bad result) gives `NOT CHECKED` and a reject. Never "eligible". (lesson 8 Nov)
- G15 Static test: `improve_gate.py` and `scripts/evaluate_candidate.py` import no local-model client, requests, urllib, socket or http. (R15)

## Risks R1-R15 (memo section 5) and the test for each
| Risk | Test in `tests/test_improve_gate.py` |
|---|---|
| R1 proposer sees dev-check | canary in candidate stops run |
| R2 held-out leak | canary scan finds a planted canary and passes clean text |
| R3 over-fit from many tries | 6 gains pass, 5 do not; cap 3; 50 do-nothing candidates x 1000 rounds, fixed seed |
| R4 memorising | 8 words rejected, 7 allowed |
| R5 hiding findings | "report nothing" text refused; stub that reports nothing loses faults and is rejected |
| R6 lost fault | stub that drops one fault is rejected |
| R7 run noise | no-op candidate rejected (B = 0) |
| R8 edits scorer, rules, log, split | stub that edits a rule file is caught; fixed target list |
| R9 log tampering | broken link in a copy: the run refuses |
| R10 lesson pile-up | 11th lesson refused |
| R11 rubber-stamp approval | NOT in this card: the human step shows diff and results together (later card) |
| R12 silent model change | NOT in this card: the model digest is a column in `agent_versions`; the check is a later card |
| R13 set too small | 20 pilot cases print "cannot pass, only 3 misses; grow the set first" |
| R14 rule changed after results | changed alpha with the old hash refused; edited protocol row refused |
| R15 model judges itself | static import scan, and the scan is shown able to fail |

## NOT done in this card
- The human step that writes `agent_versions`, and the owner signing one version before the sealed final test.
- The model proposer.
- Growing the practice set from 20 to about 90 cases, split dev-train / dev-check / regression / held-out by hash. Until then no candidate can pass: on 20 cases the gate says "cannot pass".
- The real runner hook-up. The script takes a runner as `module:function`; only stub and recorded runners are used here.
- The 10-lesson remove-one ablation each round, the audit of 1 in 5 approvals (R11), the model runtime digest check (R12).
- Paired bootstrap intervals for kappa and time.
- The large do-nothing simulation on the real set size.
- All numbers (alpha 0.05, 3 candidates, +25% time, +1 false alarm per 30) are proposals; the owner has not fixed them.
