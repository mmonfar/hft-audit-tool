# Human factors framework v0

A short list of questions a reviewer asks of three kinds of artefact: alerts, notes (EMR notes and handover) and order sets. Each question names the way it can fail for a patient or user, how it can be detected, and which catalogue rule and source back it.

It is a pre-check. It does not replace a human factors engineer. It is not a medical device and gives no clinical advice.

## Files

- `hf_framework_v0.json`: the criteria.
- `framework.py`: loads and checks the file.
- `../tests/test_framework.py`: the tests, with planted bad files in `../tests/fixtures`.

## Fields of each criterion

`id`, `artefact` (alert / note / order_set), `question`, `failure_mode`, `detect` (text_pattern / measure / human_only), `rule_id` (a rule in the rule catalogue, or null), `source` (a source id from the catalogue, or "needs source") and `fmea_fields`. A criterion with a rule_id also has `applies_to` (the item types: alert / error_message / label / note / order_set) and `applies_to_source` (the catalogue line it comes from). The referee drops a finding whose rule does not apply to the item.

`fmea_fields` holds a severity guess and the early sign a reviewer would see. It is a guess, not a score. No numbers are added up.

## Criteria count per artefact type

- alert: 10
- note: 7
- order_set: 7

The rule catalogue has no order-set rows of its own. Order-set criteria reuse the order-screen rules (EMR-01 to EMR-03, NIE-02) and add human-only questions.

## Gaps

Where no source exists the file says "needs source". It never fills the gap with a made-up citation. Alert audience and alert timing are inputs to every alert criterion. Both lists are practice, not evidence, until a source is added.

needs source count: 11

(9 criteria and the 2 alert input lists.)

## Check it

    python -m pytest -q tests/test_framework.py

The framework check also reads the rule catalogue to confirm every rule id and source id.
