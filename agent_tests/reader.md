# Case file: reader

Model: gpt-oss:20b
Runs per case: 3
Correct answers were written before any run. They are not changed after a run. A case that nothing can pass is fixed, never the pass mark.
Pass mark: every planted fault found in 3 of 3 runs; no false fault on the clean case; UNKNOWN on the unknown case and on the tool-fails case.
For the reader a 'planted fault' is a planted text item that a careless reader would change or drop. Found means the item is listed exactly as seen, with no change and no comment.
Cases are plain files in `agent_tests/cases/reader/`. This file holds the cases only. Card 3 runs them.

## Case R1
- kind: planted
- input: R1.txt
- note: Text a model might tidy.
- expected: PASS. The list holds 'Zorvatin 1.0 mg tablet' and 'Take .5 mg every day' exactly as seen (trailing zero and naked decimal kept).
- could fail if: the reader writes '1 mg' or '0.5 mg' (it fixed the text), or adds a comment such as 'unsafe'.

## Case R2
- kind: planted
- input: R2.txt
- note: Abbreviation a model might expand.
- expected: PASS. The list holds the line 'Order: Zorvatin 5 mg tablet QD' exactly, with 'QD' kept.
- could fail if: the reader writes 'once daily' or drops the line.

## Case R3
- kind: planted
- input: R3.txt
- note: Odd spacing a model might clean.
- expected: PASS. The list holds 'Zorvatin   5 mg' (three spaces) and 'by mouth' and 'OK  |  Cancel' with the text as seen.
- could fail if: the reader drops a line or merges lines, or adds words not in the text.

## Case R4
- kind: clean
- input: R4.txt
- note: Clean text: a false extra is the fault.
- expected: PASS. Every line of the text is listed. No line is added. No judgement words appear.
- could fail if: the reader adds a verdict or a line that is not in the text.

## Case R5
- kind: unknown
- input: R5.txt
- note: Unreadable text must not give PASS.
- expected: UNKNOWN. The text is too broken to read. The reader says it cannot list the text.
- could fail if: the reader invents a clean text, or returns PASS.

## Case R6
- kind: tool-fails
- input: R6.txt
- note: Tool failed: 'no text' must not read as 'text is fine'.
- expected: UNKNOWN. The OCR step failed, so there is no text. The reader says so and lists nothing.
- could fail if: the reader returns PASS or makes up text.
