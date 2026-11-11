# Role file: referee

Plain code. This role uses no model, so it has no model tag and no prompt.
MedGemma: not used

## Job
Check every suggested fault with code, and give the final state of each fault.

## Inputs
- Reads: the OCR text, the tool state for the case, the rule checker output, and the frozen rule list (`framework/hf_framework_v0.json`).
- Must not read: any model's own score, the answer key, or other cases.

## Tools
- Plain Python in the repo. No model call, no network, no tie-break by a model.
- Steps: (1) strict JSON parse, extra fields dropped; (2) the quote is found in the OCR text after white-space is fixed (runs of spaces, tabs and line breaks become one space; case is kept); (3) the rule id exists in the frozen list.

## Limits
- One pass over each fault. No retry. Same input gives the same answer every time.
- Write access: the one output file for the case only. It never edits a quote.

## Stop rule
- Stop after every fault has a state.
- If the OCR text is empty or the tool state is not ok, every fault is UNABLE TO CHECK and the first line is UNKNOWN.
- If the JSON cannot be parsed, state UNABLE TO CHECK. It never says "no findings" when a check could not run.

## Output
- File: `out/<case_id>/referee.json`.
- The first line is exactly PASS (every fault CONFIRMED, or no fault suggested on text that was read), FAIL (at least one fault DISPUTED) or UNKNOWN (UNABLE TO CHECK).
- Then one state per fault: CONFIRMED (quote found, rule id exists, code rule agrees), DISPUTED (quote found and rule id valid, but the code rule finds the fault outside the quote; shown to a human, never hidden), DROPPED (quote not found, rule id not in the list, rule does not apply to the item type, or a code check says it is not a fault; sent back to the model at most once, then shown struck through, never hidden), UNABLE TO CHECK.
- The referee has the last word. It is the only role that does.

## Checked by
A human checks a sample, and the case file `agent_tests/referee.md` (planted bad quotes and bad rule ids must give DROPPED). This role is a script, so a second model is not used as its check.
