# Spec: redesign (illustrative redesign view)

## Goal
After the findings, show what a screen could look like with the fixes applied, for CONFIRMED findings only. The poor design is shown first, then the redesign, one after the other. The view is a starting idea to react to. It is an idea to react to, not a finished design.

## Tag
Every redesign carries the tag: "Illustrative redesign. Fictional. Not a medical device." The words "Recommended", "Better" and "Approved" are never used, also in a negation.

## States
| State | Redesign | Words shown |
|---|---|---|
| CONFIRMED | yes | numbered "What changed" list |
| DISPUTED | no fix | "A human must decide." |
| Dropped | none | none |
| UNABLE TO CHECK | none | none |
| CHECKED ("no finding passed the code check") | none | none |

The table lookup is gated on state CONFIRMED in code (`redesign_table.fixes_for`).

## The rule-to-fix table
One data file: `redesign_table.py`. Row: rule id -> fix templates -> principle -> source. Fix text is fixed words. EMR-01 fix A is one of three lines, picked by the pattern in the quote (abbreviation, trailing zero, no leading zero). The only slot is `{quote}`, filled from the finding's quoted line. No model writes any fix and the file imports no model and no network code. Up to three fixes per rule; the main screen shows the first one, and the enlarge view shows all of them under the same number chip.

The number of a fix is the finding id. It is never counted again.

| Rule | Principle (own words) | Source |
|---|---|---|
| EMR-01 | Make errors hard to make; some short forms are known to be misread | ISMP error-prone abbreviations note; Nielsen heuristic 5 |
| EMR-02 | Look-alike drug names must look different | tall-man lettering note; Human Factors in Clinical Information Design, principle 8 |
| EMR-03 | A touch target must be at least 24 by 24 CSS px | WCAG 2.2 criterion 2.5.8 |
| ALT-01 | An alert names the value and the reason | Nielsen heuristic 9; Human Factors in Clinical Information Design, principle 9 |
| ALT-02 | Alerts that look alike are hard to tell apart | Human Factors in Clinical Information Design, principle 9 |
| ALT-03 | Alert fatigue | Newton et al., J Med Internet Res 2026, DOI 10.2196/78676 (alert-fatigue-hospitals-qualitative-2026) |
| LBL-18 | Text needs enough contrast against its background | WCAG 2.2 criterion 1.4.3 |

Every source above is a note on disk in the knowledge store. The notes for Nielsen, ISMP, tall-man and WCAG hold names and short summaries only; the table cites by name and number, in our own words. A row with no supporting note says "source pending".

## Screen rules (built in card 14)
- Plain cream ground. The redesign differs from the findings by the slate tag bar, the slate frame, the heading and the caption. No new colour. No "fixed" mark on a chip.
- A fix is drawn only when the table has fixed draw words for it. Otherwise: "This fix cannot be drawn. Read it in the list."
- Shown only after the findings. Phone 390 px and desktop 1366 and 1920 px.
- Numbered "What changed" list; each number is the finding number; chips match the finding boxes.
- Each item shows rule id, principle name and source.
- Look benchmark: `docs/screens/confirmed_1920.png`.

## Tests
`tests/test_redesign_table.py`.
- Table part (green now): every pilot rule has a full row; every source path exists in the knowledge store; gating by state; numbers equal the finding id; fixed-output hash; no model or network import; words check on the spec.
- Render part (card 14, `tests/test_redesign_render.py`): redesign view, tag, state cases, numbers equal finding ids, banned words, no side scroll at 390, 1366 and 1920.

## Names
Files and folders use kebab-case or the existing snake_case Python module names.
