# Case file: referee

Model: gpt-oss:20b (not run by this role: it is plain code, no model)
Runs per case: 3
Correct answers were written before any run. They are not changed after a run. A case that nothing can pass is fixed, never the pass mark.
Pass mark: every planted fault found in 3 of 3 runs; no false fault on the clean case; UNKNOWN on the unknown case and on the tool-fails case.
The referee is plain code, so the 3 runs must give the same answer every time. Input for each case is a file with the OCR text, a tool state and a list of faults in the JSON contract.
Cases are plain files in `agent_tests/cases/referee/`. This file holds the cases only. Card 3 runs them.

## Case F1
- kind: planted
- input: F1.json
- note: Planted: quote altered by one letter.
- expected: FAIL. Fault f1 is DROPPED: the quote 'Zorvatin 5 mg tablet QDD' is not in the OCR text (one extra letter).
- could fail if: the referee says CONFIRMED (its match is too loose).

## Case F2
- kind: planted
- input: F2.json
- note: Planted: made-up rule id.
- expected: FAIL. Fault f1 is DROPPED: the rule id ZZZ-99 is not in the frozen list, although the quote is in the text.
- could fail if: the referee says CONFIRMED (it does not check the id).

## Case F3
- kind: planted
- input: F3.json
- note: Planted: one good fault and one invented quote.
- expected: FAIL. The fault with a quote in the text is CONFIRMED. The fault with the quote 'This sentence is not in the text' is DROPPED. The final list shows both.
- could fail if: the made-up quote is CONFIRMED, or the DROPPED fault is hidden.

## Case F4
- kind: clean
- input: F4.json
- note: Clean: white-space differences only.
- expected: PASS. The quote matches after white-space is fixed. Fault f1 is CONFIRMED.
- could fail if: the referee disputes it because of the line breaks and spaces.

## Case F5
- kind: unknown
- input: F5.json
- note: Nothing to compare against.
- expected: UNKNOWN. The OCR text is empty, so every fault is UNABLE TO CHECK. It never says CONFIRMED or 'no findings'.
- could fail if: the referee returns PASS or CONFIRMED.

## Case F6
- kind: tool-fails
- input: F6.json
- note: Tool failed.
- expected: UNKNOWN. The tool state is 'ocr timed out', so every fault is UNABLE TO CHECK.
- could fail if: the referee returns PASS or CONFIRMED.
