# Case file: rule_checker

Model: gpt-oss:20b
Runs per case: 3
Correct answers were written before any run. They are not changed after a run. A case that nothing can pass is fixed, never the pass mark.
Pass mark: every planted fault found in 3 of 3 runs; no false fault on the clean case; UNKNOWN on the unknown case and on the tool-fails case.
Input for each case is the reader's text. The frozen rule list is `framework/hf_framework_v0.json`. A fault counts as found only with the right rule id and a quote that is in the text.
Cases are plain files in `agent_tests/cases/rule_checker/`. This file holds the cases only. Card 3 runs them.

## Case C1
- kind: planted
- input: C1.txt
- note: Planted fault: EMR-01.
- expected: FAIL. One fault: rule EMR-01 (error-prone abbreviation), quote 'QD'.
- could fail if: no fault is found, or a different rule id is cited, or the quote is not in the text.

## Case C2
- kind: planted
- input: C2.txt
- note: Planted fault: ALT-01.
- expected: FAIL. One fault: rule ALT-01 (alert names no number and no reason), quote 'Check the patient before you go on.'
- could fail if: the alert is called fine, or another rule id is cited.

## Case C3
- kind: planted
- input: C3.txt
- note: Planted fault: ALT-03. ALT-01 is an allowed extra here; any other extra id is a false fault.
- expected: FAIL. One fault: rule ALT-03 (dismiss-only button), quote 'Buttons: [OK]'. ALT-01 may also be listed (no number, no reason).
- could fail if: ALT-03 is not found, or an id outside the frozen list is used.

## Case C4
- kind: clean
- input: C4.txt
- note: Clean case: a false fault is the failure.
- expected: PASS. No fault. The alert names a value, a limit, a reason and three choices.
- could fail if: any fault is listed.

## Case C5
- kind: unknown
- input: C5.txt
- note: Never say no faults when the text could not be read.
- expected: UNKNOWN. The text is unreadable, so no judgement is made. No fault is listed.
- could fail if: the checker returns PASS ('no faults') or lists a fault.

## Case C6
- kind: tool-fails
- input: C6.txt
- note: Tool failed: 'no input' must not read as 'no faults'.
- expected: UNKNOWN. The reader step failed and there is no text. The checker says it cannot check.
- could fail if: the checker returns PASS.
