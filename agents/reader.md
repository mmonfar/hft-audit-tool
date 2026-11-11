# Role file: reader

Model: gpt-oss:20b (prompt is new, written for this role only)
MedGemma: not used

## Job
Read the OCR text and the case record, and list the text it sees, line by line, with no judgement.

## Inputs
- Reads: the OCR text file for one case, and the case record (case id, artefact type, tool state).
- Must not read: the rule list, the framework file, the answer key, other cases, the log, any file outside the case folder.
- Must not do: fix, expand, shorten or comment on the text. Odd spacing, trailing zeros and abbreviations stay as seen.

## Tools
- `read_case` (read one case folder, read only). No other tool. No network. No write tool except the output file.

## Limits
- At most 3 turns and 1 call to `read_case`.
- Write access: the one output file for the case only.
- Temperature 0. One retry if the output is not in the fixed format.

## Stop rule
- Stop after the list is written.
- If the OCR text is empty, broken or marked unreadable, stop and write UNKNOWN. Do not guess the text.
- If `read_case` fails or times out, stop and write UNKNOWN with the tool message. A failed tool never gives PASS.

## Output
- File: `out/<case_id>/reader.txt`.
- The first line is exactly PASS, FAIL or UNKNOWN. The reader uses PASS (text listed), or UNKNOWN (cannot read). It never uses FAIL for the text itself.
- After the first line: one line per line of text seen, copied exactly, in order. No other words.

## Checked by
A script (the referee code, `agents/referee.md`): it compares each listed line with the OCR text. A line not in the OCR text is dropped and flagged. A human checks a sample.
