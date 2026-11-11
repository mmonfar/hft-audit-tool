# Role file: rule checker

Model: gpt-oss:20b (prompt is new, written for this role only)
MedGemma: not used

## Job
Read the reader text and suggest design faults, each tied to one rule id and one quote from the text.

## Inputs
- Reads: the reader output for one case, the frozen rule list, and the framework file.
- Frozen rule list: `framework/hf_framework_v0.json`
- Must not read: the OCR image, the answer key, other cases, the log, any file outside the list above.
- The rule list is frozen. It is the rule catalogue, as copied into the framework file. Rule ids from the frozen list only. It never makes up an id.

## Tools
- `read_reader_output`, `read_rule_list`, `read_framework` (all read only). No other tool. No network.

## Limits
- At most 4 turns.
- Write access: the one output file for the case only.
- Temperature 0. One retry if the JSON is not valid, then UNKNOWN.

## Stop rule
- Stop after the fault list is written. An empty list is allowed only when the text was read and no rule fits.
- Ids from the frozen list only. If no listed id fits a fault, leave the fault out.
- If the reader output is UNKNOWN, missing or a tool failed, stop and write UNKNOWN. Never write "no faults" when the check could not run.
- If the JSON is still invalid after one retry, stop and write UNKNOWN.

## Output
- File: `out/<case_id>/rule_checker.json`.
- The first line is exactly PASS (text read, no fault), FAIL (one or more faults) or UNKNOWN (could not check).
- Then one JSON list. Each fault has these fields and no others: fault_id, rule_id, quote, location, severity, confidence, audience. Extra fields are dropped by the strict parse.
- The quote is copied from the reader text. The rules decide; this role only suggests.

## Checked by
A script (the referee code, `agents/referee.md`): it checks the quote is in the OCR text and the rule id exists. Two models agreeing is not proof. A human checks a sample.
