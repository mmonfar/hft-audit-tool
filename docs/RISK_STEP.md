# Risk step (hft-team-07)

Status: pre-check. Not a medical device. Does not replace a human factors engineer. NOT REVIEWED.

## What it does
It runs on each CONFIRMED or DISPUTED finding after the code referee. Dropped findings are skipped.
For each finding it shows three separate fields:

| Field | Meaning | Source |
|---|---|---|
| Severity | minor, major or critical | A table in `risk_step.py` keyed by rule id, or a human entry. Never a model. |
| Occurrence | How often it happens | On invented cases: "example, not measured". Real counts only from a later real log, always with n. |
| Detection | How the check found it | model only, quote match, or code rule. Plain labels, no numbers. |

There is no single combined number. Nothing is ranked by multiplying the three.

## Severity rules
- The table has one row per rule id. Each row has a level and a source id, or "needs source".
- Today every row says "needs source". The framework sources back the rules, not the severity levels.
- A rule with no row shows "severity: not set". It ranks last. There is no default.
- A model may propose a severity. It is shown as "PROPOSAL (model), not a score". It ranks nothing.
- A human accepts a proposal by adding a row (`fault_id`, `severity`). Only then does it rank. The source reads "human entry".

## Human severity in the log (hft-team-09)
- Table `human_severity` in the audit log: row id, decision id, fault id, reader id, severity (minor, major, critical), reason, time. A reason is required.
- Append-only, like the other tables, and every row is added to the hash chain. A changed severity is a new row, never an edit.
- `log.add_human_severity(...)` is the one way to add a row. It refuses a model or agent reader id (ids that start with model, agent, reader, referee and similar names).
- `python risk_step.py --verdicts v.json --db audit.sqlite` reads the rows. `--human file.json` still works; if both name the same fault, the log wins.
- The latest row for a fault sets the severity. The output shows "human entry", the reader id, the date and the count of earlier entries. A model severity stays "PROPOSAL (model), not a score".
- This card does not change the severity levels. A review of the levels is a separate open item.

## Ranking
1. Severity (critical, then major, then minor, then not set).
2. Weak detection first (model only, then quote match, then code rule).
3. Higher real occurrence first (invented cases all tie).
4. Ties keep input order.

## Why not one number
The reading below is from abstracts only. Full texts were not read.
- Shebl NA, Franklin BD, Barber N. 2012. BMC Health Serv Res 12:150. DOI 10.1186/1472-6963-12-150. In the abstract the authors judge the risk priority number (severity x occurrence x detection) invalid, because it multiplies ordinal scales. They found process mapping useful.
- Rangel A et al. 2026. J Appl Clin Med Phys 27(8):e70674. DOI 10.1002/acm2.70674. In the abstract, one radiotherapy exercise (9 physicists, 63 failure modes): the action priority method flagged 7 high-risk modes and the number method flagged 23 more. The authors say action priority is severity-driven and more consistent.

This is one small exercise and one paper. It does not show that action priority is better in general. No health-care failure-mode study of the HFMEA scales was found.

## Ideas taken
From `dynamic_rpn` (AGPL-3.0, read LICENSE first): the idea to show the three fields apart. No code and no text copied. A test checks that no 8-word run is shared with its source.

## Run
`python risk_step.py --selftest` and `python risk_step.py --sample`.
